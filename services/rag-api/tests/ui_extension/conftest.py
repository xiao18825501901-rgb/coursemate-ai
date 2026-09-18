import pytest
from fastapi.testclient import TestClient
from app.cm_update.app import create_app
from app.cm_update.config import Settings
from app.cm_update.seed import seed
from app.cm_update.provider import ProviderError

class ContractProvider:
    """Local contract fixture. Not a live Qwen model and not shipped as production default."""
    calls=[]
    async def generate(self,course,text,profile,sources,history,lane,bridge=None,**kwargs):
        self.calls.append({'text':text,'history':history,'sources':sources,'bridge':bridge,'lane':lane})
        yield {'kind':'status','status':'planning','label':'测试模型：生成 Prompt'}
        yield {'kind':'prompt','text':'本地测试：使用 CS3481 Word 的中文教学、英文术语、例题和互动检查方式；该内容不是千问实测。'}
        yield {'kind':'status','status':'generating','label':'测试模型：生成内容'}
        if text=='force-fail':
            yield {'kind':'delta','text':'未完成的答案'}
            raise ProviderError('TEST_FAILURE')
        answer='## Step 1 理解问题\n先识别题目给出的条件。\n## Step 2 联系知识\n这是仅用于合同测试的教学输出。'
        if text=='math-layout-fixture':answer+='\n\n$$\n\\frac{a}{b}+\\sqrt{x^2+y^2}\n$$\n\n| 符号 | 含义 |\n| --- | --- |\n| x | 输入值 |\n| y | 输出值 |'
        if sources:answer+=' [S1]'
        for part in [answer[:35],answer[35:]]:yield {'kind':'delta','text':part}
        yield {'kind':'usage','stage':'answer','value':{'input_tokens':1,'output_tokens':1}}

_SAMPLE_TEXT = (
    "Lecture 04 Clustering\n\nK-means partitions points into k clusters by minimising "
    "the within-cluster sum of squares. DBSCAN groups density-reachable points and "
    "labels the remainder as noise.\n"
)


def _sample_pdf(path) -> None:
    """Write a tiny real PDF so the standalone store has a document to serve.

    The delivered standalone fixture used the package's `sample-documents`
    directory, which is deliberately not published from this repository. The
    sample corpus is therefore generated here instead: it keeps the standalone
    tests self-contained and guarantees no demo curriculum can leak into a
    deployment.
    """

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": path.stem, "/Subject": _SAMPLE_TEXT})
    with path.open("wb") as handle:
        writer.write(handle)
    writer.close()


@pytest.fixture
def env(tmp_path):
    samples = tmp_path / "sample-documents"
    samples.mkdir(parents=True, exist_ok=True)
    for name in ("Lecture_04_Clustering.pdf", "Tutorial_01_Data_Reading.pdf"):
        _sample_pdf(samples / name)
    cfg=Settings(data_dir=tmp_path/'data',environment='test',provider_mode='test')
    seed(cfg, documents=samples)
    provider=ContractProvider();provider.calls=[]
    app=create_app(cfg,provider=provider)
    with TestClient(app) as client:
        yield app,client,provider,cfg

@pytest.fixture
def client(env):
    app,c,p,cfg=env
    assert c.post('/api/ui/v1/dev/login',json={'account':'alice'}).status_code==200
    return c

P='/api/ui/v1'
def login(c,name):assert c.post(P+'/dev/login',json={'account':name}).status_code==200
