CourseJesus Canvas 本地导入工具（Windows x64）
================================================

首次使用
1. 必须先把 ZIP 全部解压到一个普通文件夹。不要直接在压缩包预览中运行。
2. 双击 CourseJesus-Canvas-Bridge.exe。
3. 在 CourseJesus 网页打开“从 Canvas 导入”→“用本地 Token 导入”，选择学校并生成连接信息。
4. 把网页显示的整段连接信息复制到工具的“连接信息”框。
5. 在工具的“Canvas Token”框中输入你的 Personal Access Token，然后点“连接并读取课程”。
6. 工具读到课程后，回到网页选择要导入的课程。工具会继续下载并上传所选课程的文件。

重要说明
- Canvas Token 只保留在本次工具进程的内存中，不会发送给 CourseJesus，不会写入配置、日志或压缩包。
- 连接信息不含 Canvas Token，但它是一次性、短期有效的，请不要转发给别人。
- 本工具只读取已登记的 CityU / CityU(DG) Canvas，不能改成绩、交作业或执行教师操作。
- 这是未进行代码签名的便携程序。Windows 可能显示发布者未知提示；请核对网页公布的 SHA-256。不要关闭 Windows 安全功能。
- 本版本按本轮要求只完成构建，尚未进行真实 Canvas 或人工验收，也尚未部署。

高级启动（可选）
在已经解压的目录中可以使用真实存在的程序入口。
PowerShell：
  & ".\CourseJesus-Canvas-Bridge.exe" --ticket "网页复制的连接信息"
CMD：
  CourseJesus-Canvas-Bridge.exe --ticket "网页复制的连接信息"

旧版只有单个连接码时
- 把单个连接码粘贴到同一个输入框。
- 必须在窗口中明确选择 CourseJesus 服务地址和学校 Canvas；工具不会把连接码发给多个服务器猜测。

遇到问题
- “连接信息无效”：回到网页重新生成；旧连接信息不可重复使用。
- “Canvas Token 无效”：在 Canvas Account → Settings 重新生成短期 Token。
- “等待网页选择课程”：保持工具运行，回到网页勾选课程并确认。
- 不要把 Token 发送给客服、ChatGPT 或任何网页表单。
