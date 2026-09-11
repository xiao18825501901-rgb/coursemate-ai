import io
import stat
import zipfile
import zlib
from pathlib import PurePosixPath

from app.config import Settings
from app.errors import ApiError

MEDIA_TYPES: dict[str, set[str]] = {
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/plain", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",
    },
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    },
    ".doc": {"application/msword", "application/octet-stream"},
    ".xls": {"application/vnd.ms-excel", "application/octet-stream"},
    ".ppt": {"application/vnd.ms-powerpoint", "application/octet-stream"},
    ".csv": {"text/csv", "application/csv", "text/plain", "application/octet-stream"},
    ".ipynb": {
        "application/x-ipynb+json",
        "application/json",
        "application/octet-stream",
    },
    ".png": {"image/png", "application/octet-stream"},
    ".jpg": {"image/jpeg", "application/octet-stream"},
    ".jpeg": {"image/jpeg", "application/octet-stream"},
    ".gif": {"image/gif", "application/octet-stream"},
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif"}
LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls", ".ppt"}
OOXML_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
OOXML_REQUIRED_PARTS = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
    ".pptx": "ppt/presentation.xml",
}


def _invalid_office(message: str) -> ApiError:
    return ApiError(400, "INVALID_FILE_CONTENT", message)


def _validate_ooxml(extension: str, content: bytes, settings: Settings) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise _invalid_office("The file is not a valid Office ZIP document.") from error

    with archive:
        members = archive.infolist()
        if not members or len(members) > settings.v3_office_max_archive_entries:
            raise ApiError(
                400,
                "OFFICE_ARCHIVE_LIMIT_EXCEEDED",
                "The Office archive exceeds the safe processing limits.",
            )
        members_by_name: dict[str, zipfile.ZipInfo] = {}
        uncompressed_bytes = 0
        for member in members:
            name = member.filename
            path = PurePosixPath(name)
            if (
                not name
                or len(name) > 512
                or "\\" in name
                or "\x00" in name
                or path.is_absolute()
                or ".." in path.parts
                or any(":" in part for part in path.parts)
                or stat.S_ISLNK(member.external_attr >> 16)
                or member.flag_bits & 0x1
            ):
                raise ApiError(
                    400,
                    "UNSAFE_OFFICE_ARCHIVE",
                    "The Office archive contains an unsafe entry.",
                )
            normalized = path.as_posix().lower()
            if normalized in members_by_name:
                raise ApiError(
                    400,
                    "UNSAFE_OFFICE_ARCHIVE",
                    "The Office archive contains a duplicate entry.",
                )
            members_by_name[normalized] = member
            if normalized.endswith("vbaproject.bin") or "macroenabled" in normalized:
                raise ApiError(
                    400,
                    "OFFICE_MACROS_NOT_ALLOWED",
                    "Macro-enabled Office files are not accepted.",
                )
            uncompressed_bytes += member.file_size
            ratio = member.file_size / max(member.compress_size, 1)
            if (
                uncompressed_bytes > settings.v3_office_max_uncompressed_bytes
                or (member.file_size >= 1_024 and ratio > settings.v3_office_max_compression_ratio)
            ):
                raise ApiError(
                    400,
                    "OFFICE_ARCHIVE_LIMIT_EXCEEDED",
                    "The Office archive exceeds the safe processing limits.",
                )

        content_types = members_by_name.get("[content_types].xml")
        if content_types is None or OOXML_REQUIRED_PARTS[extension] not in members_by_name:
            raise _invalid_office("The file does not contain the required Office document parts.")
        try:
            content_type_xml = archive.read(content_types).lower()
            corrupt_member = archive.testzip()
        except (EOFError, NotImplementedError, RuntimeError, zipfile.BadZipFile) as error:
            raise _invalid_office("The Office archive could not be validated.") from error
        if b"macroenabled" in content_type_xml or b"vbaproject" in content_type_xml:
            raise ApiError(
                400,
                "OFFICE_MACROS_NOT_ALLOWED",
                "Macro-enabled Office files are not accepted.",
            )
        if corrupt_member is not None:
            raise _invalid_office("The Office archive contains corrupt data.")


def _jpeg_dimensions(content: bytes) -> tuple[int, int] | None:
    if not content.startswith(b"\xff\xd8"):
        return None
    position = 2
    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while position + 4 <= len(content):
        if content[position] != 0xFF:
            position += 1
            continue
        while position < len(content) and content[position] == 0xFF:
            position += 1
        if position >= len(content):
            break
        marker = content[position]
        position += 1
        if marker in {0x01, *range(0xD0, 0xD9)}:
            continue
        if position + 2 > len(content):
            break
        length = int.from_bytes(content[position : position + 2], "big")
        if length < 2 or position + length > len(content):
            return None
        if marker in start_of_frame and length >= 7:
            height = int.from_bytes(content[position + 3 : position + 5], "big")
            width = int.from_bytes(content[position + 5 : position + 7], "big")
            return width, height
        position += length
    return None


def _image_dimensions(extension: str, content: bytes) -> tuple[int, int] | None:
    if extension == ".png":
        if len(content) < 24 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        return (
            int.from_bytes(content[16:20], "big"),
            int.from_bytes(content[20:24], "big"),
        )
    if extension == ".gif":
        if len(content) < 10 or content[:6] not in {b"GIF87a", b"GIF89a"}:
            return None
        return (
            int.from_bytes(content[6:8], "little"),
            int.from_bytes(content[8:10], "little"),
        )
    return _jpeg_dimensions(content)


def _valid_png(content: bytes) -> bool:
    position = 8
    first = True
    while position + 12 <= len(content):
        length = int.from_bytes(content[position : position + 4], "big")
        chunk_end = position + 12 + length
        if chunk_end > len(content):
            return False
        chunk_type = content[position + 4 : position + 8]
        chunk_data = content[position + 8 : position + 8 + length]
        expected_crc = int.from_bytes(content[position + 8 + length : chunk_end], "big")
        if first and (chunk_type != b"IHDR" or length != 13):
            return False
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            return False
        first = False
        position = chunk_end
        if chunk_type == b"IEND":
            return length == 0 and position == len(content)
    return False


def _valid_image_container(extension: str, content: bytes) -> bool:
    if extension == ".png":
        return _valid_png(content)
    if extension == ".gif":
        return content.endswith(b";")
    return content.endswith(b"\xff\xd9")


def validate_file_content(extension: str, content: bytes, settings: Settings) -> None:
    if extension == ".pdf" and not content.startswith(b"%PDF"):
        raise ApiError(400, "INVALID_FILE_CONTENT", "The file does not contain a PDF header.")
    if extension in OOXML_EXTENSIONS:
        _validate_ooxml(extension, content, settings)
    if extension in LEGACY_OFFICE_EXTENSIONS and not content.startswith(
        bytes.fromhex("D0CF11E0A1B11AE1")
    ):
        raise ApiError(
            400,
            "INVALID_FILE_CONTENT",
            "The file is not a legacy Office compound document.",
        )
    if extension in IMAGE_EXTENSIONS:
        dimensions = _image_dimensions(extension, content)
        if dimensions is None or min(dimensions) < 1:
            raise ApiError(
                400,
                "INVALID_FILE_CONTENT",
                "The file does not contain a supported image header.",
            )
        if (
            max(dimensions) > settings.v3_preview_max_image_dimension
            or dimensions[0] * dimensions[1] > settings.v3_preview_max_image_pixels
        ):
            raise ApiError(
                400,
                "IMAGE_DIMENSIONS_TOO_LARGE",
                "The image dimensions exceed the preview safety limit.",
            )
        if not _valid_image_container(extension, content):
            raise ApiError(
                400,
                "INVALID_FILE_CONTENT",
                "The image container is incomplete or corrupt.",
            )
