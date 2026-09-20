import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API="http://127.0.0.1:8200/ui-extension/api/ui/v1";
const auth={Authorization:"Bearer test-session-token"};
const unverified={Authorization:"Bearer audit-unverified-token"};
const windowAuth={Authorization:"Bearer audit-windows-token"};
const answerCanary="MinPts 增大，聚类更保守，噪声点倾向增多";

async function post(request:APIRequestContext,path:string,data:unknown={},headers=auth) {
  const response=await request.post(API+path,{headers,data});
  expect(response.ok(),await response.text()).toBeTruthy();
  return response.json();
}
async function terminal(request:APIRequestContext,id:string,headers=auth) {
  await expect.poll(async()=>{
    const response=await request.get(API+"/runs/"+id,{headers});
    expect(response.ok()).toBeTruthy();return (await response.json()).status;
  }).toBe("completed");
}
async function learn(page:Page,request:APIRequestContext,headers=auth) {
  const layout=await (await request.get(API+"/courses/cs3481/layout",{headers})).json();
  const restore=layout.teach_conversation||layout.problem_conversation
    ?page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/courses/cs3481/layout")):null;
  const listed=page.waitForResponse(r=>r.url().endsWith("/pairs?course_id=cs3481"));
  await page.goto("/app#/course/cs3481/learn");
  await listed;if(restore) expect((await restore).ok()).toBeTruthy();
  await expect(page.getByLabel("知识学习输入")).toBeVisible();
}
async function newPair(page:Page,lane:string) {
  const created=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/pairs"));
  const saved=page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/courses/cs3481/layout"));
  await page.locator(".pane-"+lane).getByRole("button",{name:"新对话",exact:true}).click();
  expect((await saved).ok()).toBeTruthy();
  return (await (await created).json()).id as string;
}
test.beforeEach(async({page})=>{
  await page.route("**/*",route=>{
    const url=new URL(route.request().url());
    if (!["127.0.0.1","localhost"].includes(url.hostname)) return route.abort("blockedbyclient");
    return route.continue();
  });
});

test("production shell sends normal and Thinking modes through integrated services",async({page,request},info)=>{
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await learn(page,request);
  await newPair(page,"teach");
  for(const mode of ["normal","thinking"]) {
    if(mode==="thinking") await page.getByRole("button",{name:"思考模式"}).click();
    await page.getByLabel("知识学习输入").fill(`Synthetic ${mode}: explain DBSCAN core points.`);
    const pending=page.waitForResponse(r=>r.request().method()==="POST"&&/\/conversations\/[^/]+\/runs$/.test(r.url()));
    await page.getByRole("button",{name:"发送知识问题"}).click();
    const response=await pending;
    expect(response.ok(),await response.text()).toBeTruthy();
    expect(response.request().postDataJSON().teaching_mode).toBe(mode);
    const run=await response.json();await terminal(request,run.id);
    await expect(page.locator(".pane-teach .chat-message-new.assistant")).toHaveCount(mode==="normal"?1:2);
    await expect(page.getByRole("button",{name:"停止生成"})).toHaveCount(0);
  }
  expect(errors).toEqual([]);
  await page.screenshot({path:info.outputPath("normal-thinking.png"),fullPage:true});
});

test("reload preserves current Pair and generated answer stays hidden until reveal",async({page,request},info)=>{
  const pairA=await post(request,"/courses/cs3481/nodes/e2e-tree-kmeans/open");
  await terminal(request,pairA.run);
  await post(request,"/courses/cs3481/nodes/e2e-tree-clustering/open");
  await learn(page,request);
  await page.locator(".pane-teach").getByRole("button",{name:"历史对话"}).click();
  const selected=page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/courses/cs3481/layout"));
  await page.locator(".history-item").filter({hasText:"K-means 聚类"}).click();
  expect((await selected).ok()).toBeTruthy();
  const restored=page.waitForResponse(r=>r.url().endsWith("/pairs/"+pairA.pair_id));
  await page.reload();await expect(page.getByLabel("知识学习输入")).toBeVisible();
  expect((await restored).ok()).toBeTruthy();
  await expect(page.locator(".pane-teach .chat-message-new.assistant")).not.toHaveCount(0);
  const pending=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/courses/cs3481/exercises"));
  await page.getByRole("button",{name:"做一题",exact:true}).click();
  const response=await pending;
  expect(response.ok(),await response.text()).toBeTruthy();
  expect(response.request().postDataJSON().pair_id).toBe(pairA.pair_id);
  const run=await response.json();await terminal(request,run.id);
  await expect(page.locator(".pane-problem")).toContainText("诊断题 · K-means 聚类");
  await expect(page.getByRole("button",{name:"显示答案",exact:true}).last()).toBeVisible();
  const saved=await request.get(API+"/pairs/"+pairA.pair_id,{headers:auth});
  const history=await saved.json();
  const exercise=history.problem.messages.find((m:any)=>m.exercise).exercise;
  for(const path of ["/runs/"+run.id,"/runs/"+run.id+"/events","/pairs/"+pairA.pair_id,"/exercises/"+exercise]) {
    const hidden=await request.get(API+path,{headers:auth});
    expect(hidden.ok()).toBeTruthy();expect(await hidden.text()).not.toContain(answerCanary);
  }
  await expect(page.locator("body")).not.toContainText(answerCanary);
  await page.getByRole("button",{name:"显示答案",exact:true}).last().click();
  await expect(page.locator(".exercise-steps")).toContainText(answerCanary);
  await page.reload();await expect(page.locator(".exercise-steps")).toContainText(answerCanary);
  await page.screenshot({path:info.outputPath("pair-reload-reveal.png"),fullPage:true});
});

test("supplied problem exposes steps and opens explanation",async({page,request},info)=>{
  await learn(page,request);
  const pairId=await newPair(page,"problem");
  await expect(page.locator(".pane-problem .chat-message-new")).toHaveCount(0);
  await page.getByLabel("题目应对输入").fill("Synthetic supplied problem: classify a point with five neighbours and MinPts=4.");
  const pending=page.waitForResponse(r=>r.request().method()==="POST"&&/\/conversations\/[^/]+\/runs$/.test(r.url()));
  await page.getByRole("button",{name:"发送题目",exact:true}).click();
  const response=await pending;expect(response.ok(),await response.text()).toBeTruthy();
  const run=await response.json();await terminal(request,run.id);
  const pair=await (await request.get(API+"/pairs/"+pairId,{headers:auth})).json();
  expect(pair.problem.conversation.id).toBe(response.url().split("/conversations/")[1].split("/")[0]);
  expect(pair.problem.messages.filter((m:any)=>m.role==="assistant")).toHaveLength(1);
  expect(pair.problem.messages.find((m:any)=>m.role==="assistant").exercise).toBeTruthy();
  await expect(page.locator(".pane-problem")).toContainText("Step 1");
  const knowledgeLinks=page.locator(".pane-problem .step-link");
  await expect(knowledgeLinks).toHaveCount(4);
  await expect(page.locator(".pane-problem").getByRole("button",{name:"详解",exact:true}).first()).toBeVisible();
  await page.locator(".pane-problem").getByRole("button",{name:"详解",exact:true}).first().click();
  const dialog=page.getByRole("dialog",{name:/详解 · 第/});
  await expect(dialog).toContainText("本地测试详解");
  await dialog.getByRole("button",{name:"关闭详解"}).click();
  const bridged=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/courses/cs3481/bridges"));
  await knowledgeLinks.first().click();
  expect((await bridged).ok()).toBeTruthy();
  await expect(page.locator(".bridge-banner")).toContainText("返回原题 · 第 1 步");
  await expect(page.locator(".pane-teach .chat-message-new.assistant")).toHaveCount(1);
  await expect(page.getByRole("button",{name:"停止生成"})).toHaveCount(0);
  const returned=page.waitForResponse(r=>r.request().method()==="PATCH"&&/\/bridges\/[^/]+\/return$/.test(r.url()));
  await page.locator(".bridge-banner").click();
  expect((await returned).ok()).toBeTruthy();
  await expect(page.locator(".bridge-banner")).toHaveCount(0);
  await page.screenshot({path:info.outputPath("supplied-explanation.png"),fullPage:true});
});

test("directory can be browsed and paginated before searching",async({page},info)=>{
  await page.goto("/app#/inbox");
  await page.getByRole("button",{name:"写信息",exact:true}).click();
  await expect(page.getByLabel("查找收件人")).toHaveValue("");
  await expect(page.locator(".person-option")).toHaveCount(20);
  const firstPage=await page.locator(".person-option").allTextContents();
  await page.getByRole("button",{name:"下一页用户"}).click();
  await expect(page.locator(".person-option")).toHaveCount(6);
  expect(await page.locator(".person-option").allTextContents()).not.toEqual(firstPage);
  await page.getByLabel("查找收件人").fill("Directory Student 24");
  await expect(page.locator(".person-option")).toHaveCount(1);
  await expect(page.locator(".person-option")).toContainText("Directory Student 24");
  await page.screenshot({path:info.outputPath("directory.png"),fullPage:true});
});

test("unverified synthetic actor cannot access campus content or trigger learning",async({request})=>{
  const me=await request.get(API+"/me/verification",{headers:unverified});
  expect(me.ok()).toBeTruthy();expect((await me.json()).verified).toBe(false);
  expect((await request.get(API+"/courses/cs3481",{headers:unverified})).status()).toBe(200);
  for(const path of ["/courses/cs3481/files","/courses/cs3481/knowledge","/courses/cs3481/comments","/courses/cs3481/layout"]) {
    const response=await request.get(API+path,{headers:unverified});expect(response.status(),path).toBe(403);
  }
  const exercise=await request.post(API+"/courses/cs3481/exercises",{headers:unverified,data:{request_id:"unverified-browser-exercise"}});
  expect(exercise.status()).toBe(403);
  const pair=await request.post(API+"/pairs",{headers:unverified,data:{course:"cs3481"}});
  expect(pair.status()).toBe(403);
});

test("calendar uses the integrated Node task store",async({page,request},info)=>{
  await page.goto("/app#/calendar");
  await page.getByRole("button",{name:/新建安排/}).click();
  const modal=page.locator(".modal"),title="Synthetic audit study plan";
  await modal.locator('input[name="title"]').fill(title);
  await modal.locator('input[name="date"]').fill("2026-10-01");
  const created=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/tasks"));
  await modal.getByRole("button",{name:/保存安排/}).click();
  const response=await created;expect(response.status(),await response.text()).toBe(201);
  const task=await response.json();
  await page.reload();
  await expect(page.locator(".task-card").filter({hasText:title})).toHaveCount(1);
  const listed=await request.get("http://127.0.0.1:8201/api/tasks?page=1&pageSize=100",{headers:auth});
  expect(listed.ok()).toBeTruthy();expect((await listed.json()).items.some((item:any)=>item.id===task.id&&item.title===title)).toBe(true);
  await page.getByRole("button",{name:`完成 ${title}`}).click();
  await expect.poll(async()=>{
    const listed=await request.get("http://127.0.0.1:8201/api/tasks?page=1&pageSize=100",{headers:auth});
    return (await listed.json()).items.find((item:any)=>item.id===task.id)?.status;
  }).toBe("completed");
  await page.screenshot({path:info.outputPath("integrated-node-plan.png"),fullPage:true});
});

test("late initial Pair response cannot replace an explicitly created new Pair",async({page,request})=>{
  const old=await post(request,"/courses/cs3481/nodes/e2e-tree-kmeans/open");
  await terminal(request,old.run);
  const oldPair=await (await request.get(API+"/pairs/"+old.pair_id,{headers:auth})).json();
  const layout=await request.put(API+"/courses/cs3481/layout",{headers:auth,data:{
    ratio:.5,teach_conversation:oldPair.teach.conversation.id,problem_conversation:null,active_node:"e2e-tree-kmeans"}});
  expect(layout.ok()).toBeTruthy();
  let markHeld!:()=>void,release!:()=>void;
  const held=new Promise<void>(resolve=>markHeld=resolve);
  const unlocked=new Promise<void>(resolve=>release=resolve);
  await page.route(API+"/pairs/"+old.pair_id,async route=>{
    const response=await route.fetch();markHeld();await unlocked;await route.fulfill({response});
  },{times:1});
  await page.goto("/app#/course/cs3481/learn");
  await held;
  const pairId=await newPair(page,"teach");
  const restored=page.waitForResponse(r=>r.url()===API+"/pairs/"+old.pair_id);
  release();await restored;
  // Let response handlers and the ensuing React render finish, without a timed sleep.
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  await expect(page.locator(".pane-teach .chat-message-new")).toHaveCount(0);
  const conversation=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/conversations"));
  await page.getByLabel("知识学习输入").fill("Synthetic new Pair after delayed restoration.");
  await page.getByRole("button",{name:"发送知识问题"}).click();
  const response=await conversation;expect(response.ok()).toBeTruthy();
  expect(response.request().postDataJSON().pair_id).toBe(pairId);
});

test("keyboard controls persist divider position and mobile panes remain usable",async({page,request},info)=>{
  await learn(page,request);
  const thinking=page.getByRole("button",{name:"思考模式"});
  await expect(thinking).toHaveAttribute("aria-pressed","false");
  await thinking.focus();await page.keyboard.press("Space");
  await expect(thinking).toHaveAttribute("aria-pressed","true");
  await page.keyboard.press("Space");await expect(thinking).toHaveAttribute("aria-pressed","false");
  const divider=page.getByRole("separator",{name:"调整学习双栏比例"});
  const before=Number(await divider.getAttribute("aria-valuenow"));
  const saved=page.waitForResponse(r=>r.request().method()==="PUT"&&r.url().endsWith("/courses/cs3481/layout"));
  await divider.focus();await page.keyboard.press(before<70?"ArrowRight":"ArrowLeft");
  expect((await saved).ok()).toBeTruthy();
  const value=await divider.getAttribute("aria-valuenow");expect(Number(value)).not.toBe(before);
  await page.reload();await expect(divider).toHaveAttribute("aria-valuenow",value!);
  await page.getByRole("button",{name:"全屏学习",exact:true}).focus();await page.keyboard.press("Enter");
  await expect(page.locator(".learn-new")).toHaveClass(/focus-mode/);
  await page.keyboard.press("Escape");await expect(page.locator(".learn-new")).not.toHaveClass(/focus-mode/);
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByLabel("知识学习输入")).toBeVisible();
  await expect(page.getByLabel("题目应对输入")).toBeHidden();
  await page.locator(".mobile-pane-tabs").getByRole("button",{name:"题目应对"}).focus();await page.keyboard.press("Enter");
  await expect(page.getByLabel("题目应对输入")).toBeVisible();
  await expect(page.getByLabel("知识学习输入")).toBeHidden();
  await expect(page.getByRole("button",{name:"做一题",exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath("mobile-controls.png"),fullPage:true});
});

test("attachment action is reachable and operable from the composer by keyboard",async({page,request})=>{
  await learn(page,request);
  await page.getByLabel("知识学习输入").focus();await page.keyboard.press("Tab");
  expect(await page.evaluate(()=>Boolean(document.activeElement?.closest(".attach-button")))).toBe(true);
  const picker=page.waitForEvent("filechooser");await page.keyboard.press("Enter");
  const chooser=await picker;expect(chooser.isMultiple()).toBe(false);
});

test("files page upload action is keyboard focusable and opens its picker",async({page})=>{
  await page.goto("/app#/course/cs3481/files");
  const upload=page.locator(".section-heading").getByText("添加我的资料",{exact:true});
  await expect(upload).toBeVisible();
  expect(await upload.evaluate(element=>(element as HTMLElement).tabIndex)).toBeGreaterThanOrEqual(0);
  await upload.focus();const picker=page.waitForEvent("filechooser");await page.keyboard.press("Enter");
  expect((await picker).isMultiple()).toBe(false);
});

test("step windows are nonmodal draggable resizable reusable and mobile bounded",async({page,request},info)=>{
  // Separate explicitly verified actor keeps real eight-per-minute limits intact.
  await page.route(API+"/**",route=>route.continue({headers:{...route.request().headers(),authorization:windowAuth.Authorization}}));
  const pair=await post(request,"/pairs",{course:"cs3481"},windowAuth);
  const conversation=await post(request,"/conversations",{course:"cs3481",lane:"problem",pair_id:pair.id},windowAuth);
  const run=await post(request,`/conversations/${conversation.id}/runs`,{text:"Synthetic two step problem for window audit",request_id:"window-audit"},windowAuth);
  await terminal(request,run.id,windowAuth);
  expect((await request.put(API+"/courses/cs3481/layout",{headers:windowAuth,data:{ratio:.5,teach_conversation:null,problem_conversation:conversation.id,active_node:null}})).ok()).toBeTruthy();
  await learn(page,request,windowAuth);
  const stepButtons=page.locator(".pane-problem").getByRole("button",{name:"详解",exact:true});
  await expect(stepButtons).toHaveCount(4);
  await stepButtons.nth(0).click();
  const first=page.getByRole("dialog",{name:"详解 · 第 1 步",exact:true});
  await expect(first).toContainText("本地测试详解");
  await expect(first).not.toHaveAttribute("aria-modal","true");
  await stepButtons.nth(1).click();
  const second=page.getByRole("dialog",{name:"详解 · 第 2 步",exact:true});
  await expect(second).toContainText("本地测试详解");
  await expect(page.locator(".explain-window")).toHaveCount(2);
  const old=await second.boundingBox(),head=await second.locator(".explain-head").boundingBox();
  await page.mouse.move(head!.x+50,head!.y+20);await page.mouse.down();await page.mouse.move(head!.x+110,head!.y+50);await page.mouse.up();
  expect((await second.boundingBox())!.x).toBeGreaterThan(old!.x+40);
  const move=second.locator(".explain-head");
  expect(await move.evaluate(element=>(element as HTMLElement).tabIndex)).toBeGreaterThanOrEqual(0);
  await move.focus();const keyboardX=(await second.boundingBox())!.x;await page.keyboard.press("ArrowLeft");
  await expect.poll(async()=>(await second.boundingBox())!.x).toBeLessThan(keyboardX);
  const handle=await second.getByLabel("调整窗口大小").boundingBox();
  const oldWidth=(await second.boundingBox())!.width;
  await page.mouse.move(handle!.x+8,handle!.y+8);await page.mouse.down();await page.mouse.move(handle!.x+68,handle!.y+48);await page.mouse.up();
  expect((await second.boundingBox())!.width).toBeGreaterThan(oldWidth+40);
  const resize=second.getByLabel("调整窗口大小");
  expect.soft(await resize.evaluate(element=>(element as HTMLElement).tabIndex),"Resize must be keyboard focusable").toBeGreaterThanOrEqual(0);
  await resize.focus();const keyboardWidth=(await second.boundingBox())!.width;
  await page.keyboard.press("ArrowRight");
  await expect.configure({soft:true}).poll(async()=>(await second.boundingBox())!.width,{message:"ArrowRight must resize the focused step window"}).toBeGreaterThan(keyboardWidth);
  await second.getByRole("button",{name:"关闭详解"}).focus();await page.keyboard.press("Enter");
  await expect(second).toHaveCount(0);await expect(first).toBeVisible();
  await page.getByLabel("知识学习输入").fill("Underlying pane remains interactive");
  await expect(page.getByLabel("知识学习输入")).toHaveValue("Underlying pane remains interactive");
  const reused=page.waitForResponse(r=>r.request().method()==="GET"&&/\/explanations\/[^/]+$/.test(r.url()));
  await stepButtons.nth(1).click();expect((await reused).ok()).toBeTruthy();await expect(second).toContainText("本地测试详解");
  await second.getByLabel("追问",{exact:true}).fill("Synthetic follow-up on this exact step");
  await second.getByRole("button",{name:"追问",exact:true}).click();
  await expect(second).toContainText("Synthetic follow-up on this exact step");
  await expect(second.getByRole("button",{name:"停止",exact:true})).toHaveCount(0);
  await page.screenshot({path:info.outputPath("desktop-step-windows.png"),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  const mobile=await second.boundingBox();expect(mobile!.x).toBeGreaterThanOrEqual(0);expect(mobile!.x+mobile!.width).toBeLessThanOrEqual(390);
  await second.getByRole("button",{name:"关闭详解"}).click();await expect(first).toBeVisible();
  await first.getByRole("button",{name:"关闭详解"}).click();await expect(page.locator(".explain-window")).toHaveCount(0);
  await page.screenshot({path:info.outputPath("mobile-step-windows-closed.png"),fullPage:true});
});

test("browser sender shares frozen files and recipient explicitly joins independent course",async({page,request,browser},info)=>{
  const course=await post(request,"/courses",{name:"Synthetic browser shared snapshot"});
  const raw="BROWSER_SNAPSHOT_CANARY original frozen private lesson.";
  const upload=await request.post(API+`/courses/${course.id}/files`,{headers:auth,multipart:{file:{name:"browser-snapshot.txt",mimeType:"text/plain",buffer:Buffer.from(raw)}}});
  expect(upload.status(),await upload.text()).toBe(201);const original=await upload.json();
  await page.goto("/app#/inbox");await page.getByRole("button",{name:"共享课程",exact:true}).click();
  const wizard=page.getByRole("dialog",{name:"共享课程",exact:true});
  await wizard.locator(".node-picker-row").filter({hasText:course.name}).click();
  await wizard.getByLabel("查找收件人").fill("Audit Unverified");
  await wizard.locator(".person-option").filter({hasText:"Audit Unverified"}).click();
  await wizard.getByRole("button",{name:"下一步",exact:true}).click();
  await wizard.getByLabel("全部不发送",{exact:true}).check();
  await wizard.getByRole("button",{name:"下一步",exact:true}).click();
  await expect(wizard).toContainText("文件：1 个");
  const sent=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/shares"));
  await wizard.getByRole("button",{name:"确认发送",exact:true}).click();
  const response=await sent;expect(response.status(),await response.text()).toBe(201);const share=await response.json();
  expect(share.files_copied).toBe(1);await expect(wizard).toHaveCount(0);
  expect((await request.delete(API+`/courses/${course.id}/files/${original.id}`,{headers:auth})).ok()).toBeTruthy();
  expect((await request.get(API+`/courses/${course.id}`,{headers:unverified})).status()).toBe(404);
  const before=await (await request.get(API+"/courses",{headers:unverified})).json();
  expect(before.some((item:any)=>item.display_type==="shared")).toBe(false);
  const recipient=await browser.newContext({viewport:{width:1440,height:1000}});
  const recipientPage=await recipient.newPage();
  await recipientPage.route("**/*",route=>{
    const url=new URL(route.request().url());
    if(!["localhost","127.0.0.1"].includes(url.hostname))return route.abort();
    // Switch only the explicitly seeded synthetic actor; real backend auth remains enforced.
    return route.continue(url.href.startsWith(API)?{headers:{...route.request().headers(),authorization:unverified.Authorization}}:{});
  });
  try {
    await recipientPage.goto("http://127.0.0.1:5373/app#/inbox");
    await recipientPage.getByRole("button",{name:"共享",exact:true}).click();
    await expect(recipientPage.getByRole("button",{name:"共享",exact:true})).toHaveClass("active");
    const card=recipientPage.locator(".inbox-share-item").filter({hasText:course.name});
    await expect(card).toContainText("1 个文件");
    const joined=recipientPage.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith(`/shares/${share.id}/join`));
    await card.getByRole("button",{name:"加入所有课程",exact:true}).click();
    const joinResponse=await joined;expect(joinResponse.ok(),await joinResponse.text()).toBeTruthy();
    const target=(await joinResponse.json()).joined_course_id;
    await expect(card).toContainText("已加入");
    await recipientPage.goto(`http://127.0.0.1:5373/app#/course/${target}/files`);
    await recipientPage.getByRole("button",{name:"我的上传",exact:true}).click();
    await recipientPage.getByRole("button",{name:/^browser-snapshot\.txt/}).click();
    const preview=recipientPage.getByRole("dialog",{name:"browser-snapshot.txt",exact:true});
    await expect(preview.locator(".text-preview")).toContainText(raw);
    const downloading=recipientPage.waitForEvent("download");
    await preview.getByRole("button",{name:"下载",exact:true}).click();
    const download=await downloading;expect(download.suggestedFilename()).toBe("browser-snapshot.txt");
    const stream=await download.createReadStream();const chunks:Buffer[]=[];for await(const chunk of stream!)chunks.push(Buffer.from(chunk));
    expect(Buffer.concat(chunks).toString()).toBe(raw);
    const files=await (await request.get(API+`/courses/${target}/files`,{headers:unverified})).json();
    expect(files).toHaveLength(1);expect(files[0].id).not.toBe(original.id);
    expect((await request.get(API+`/courses/${target}/files/${files[0].id}/content`,{headers:auth})).status()).toBe(404);
    await recipientPage.reload();await recipientPage.getByRole("button",{name:"我的上传",exact:true}).click();
    await expect(recipientPage.getByRole("button",{name:/^browser-snapshot\.txt/})).toBeVisible();
    await recipientPage.screenshot({path:info.outputPath("joined-shared-files.png"),fullPage:true});
  } finally {await recipient.close();}
});

test("long shared course identity stays readable or accessibly abbreviated in narrow sidebar",async({page,request},info)=>{
  const name="SyntheticSharedCourse_AdvancedDataScienceAndStatisticalLearning_IndependentSnapshot";
  const source=await post(request,"/courses",{name:"Sidebar audit source"});
  const renamed=await request.patch(API+`/courses/${source.id}`,{headers:auth,data:{name}});
  expect(renamed.ok(),await renamed.text()).toBeTruthy();
  const people=await (await request.get(API+"/people?q=Audit%20Unverified",{headers:auth})).json();
  expect(people).toHaveLength(1);
  const share=await post(request,"/shares",{course:source.id,recipients:[people[0].id],history_scope:"none",request_id:"sidebar-long-identity"});
  const joined=await post(request,`/shares/${share.id}/join`,{},unverified);
  const response=await request.get(API+`/courses/${joined.joined_course_id}`,{headers:unverified});
  expect(response.ok()).toBeTruthy();const course=await response.json();
  expect(course.name).toBe(name);expect(course.code.length).toBeGreaterThan(20);
  await page.route(API+"/**",route=>route.continue({headers:{...route.request().headers(),authorization:unverified.Authorization}}));
  await page.goto(`/app#/course/${course.id}/files`);
  for(const width of [1100,768]) {
    await page.setViewportSize({width,height:900});
    const sidebar=page.locator(".course-side");await expect(sidebar).toBeVisible();
    await page.screenshot({path:info.outputPath(`long-sidebar-${width}.png`),fullPage:true});
    for(const fullText of [course.name,course.code]) {
      const label=sidebar.getByText(fullText,{exact:true});await expect(label).toHaveCount(1);
      const measured=await label.evaluate(element=>{
        const el=element as HTMLElement,style=getComputedStyle(el),box=el.getBoundingClientRect();
        const side=el.closest(".course-side")!.getBoundingClientRect();
        return {client:el.clientWidth,scroll:el.scrollWidth,overflow:style.overflowX,ellipsis:style.textOverflow,
          tabIndex:el.tabIndex,title:el.title,ariaLabel:el.getAttribute("aria-label"),inside:box.left>=side.left&&box.right<=side.right};
      });
      await info.attach(`identity-${width}-${fullText===course.code?"code":"name"}`,{body:JSON.stringify(measured),contentType:"application/json"});
      expect.soft(measured.inside,"Identity container must stay inside the sidebar").toBe(true);
      const clipped=measured.scroll>measured.client+1;
      if(clipped) {
        expect.soft(measured.ellipsis,"Overflowing identity must show an intentional ellipsis, not silent clipping").toBe("ellipsis");
        expect.soft(["hidden","clip"].includes(measured.overflow)).toBe(true);
        expect.soft(measured.tabIndex,"Abbreviated identity must be reachable by keyboard").toBeGreaterThanOrEqual(0);
        expect.soft([measured.title,measured.ariaLabel].some(value=>value?.includes(fullText)),"Abbreviated identity needs its complete accessible text").toBe(true);
        if(measured.tabIndex>=0) {await label.focus();await expect(label).toBeFocused();expect(await label.ariaSnapshot()).toContain(fullText);}
      }
    }
    expect(new URL(page.url()).hash).toBe(`#/course/${course.id}/files`);
  }
  await page.setViewportSize({width:390,height:844});await expect(page.locator(".course-side")).toBeHidden();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  const unchanged=await (await request.get(API+`/courses/${course.id}`,{headers:unverified})).json();
  expect({id:unchanged.id,code:unchanged.code,name:unchanged.name}).toEqual({id:course.id,code:course.code,name});
});

test("course form directly creates a legal 100 character name and opens its bounded ID",async({page,request},info)=>{
  const name="CS3481_"+"AdvancedDataScience".repeat(5).slice(0,93);
  expect(name).toHaveLength(100);
  await page.goto("/app#/courses");
  await page.getByRole("button",{name:"创建课程",exact:true}).click();
  const form=page.getByRole("dialog",{name:"创建你的课程",exact:true});
  const input=form.locator('input[name="name"]');
  await expect(input).toHaveAttribute("maxlength","100");
  await input.fill(name);await expect(input).toHaveValue(name);
  const created=page.waitForResponse(r=>r.request().method()==="POST"&&r.url()===API+"/courses");
  await form.getByRole("button",{name:"创建课程",exact:true}).click();
  const response=await created;
  expect(response.request().postDataJSON().name).toBe(name);
  expect(response.status(),await response.text()).toBe(201);
  const course=await response.json();
  expect(course.name).toBe(name);
  expect(course.id).toMatch(/^[a-z0-9][a-z0-9-]{1,49}$/);
  await expect(form).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`#/course/${course.id}/files$`));
  await expect(page.getByRole("heading",{name:"文件",exact:true})).toBeVisible();
  await expect(page.locator(".course-side").getByText(name,{exact:true})).toBeVisible();
  const detail=await request.get(API+`/courses/${course.id}`,{headers:auth});
  expect(detail.ok()).toBeTruthy();expect((await detail.json()).name).toBe(name);
  const listed=await (await request.get(API+"/courses",{headers:auth})).json();
  expect(listed.find((item:any)=>item.id===course.id)).toMatchObject({name,pinned:true});
  expect((await request.get(API+`/courses/${course.id}`,{headers:unverified})).status()).toBe(404);
  await page.reload();
  await expect(page.locator(".course-side").getByText(name,{exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath("direct-long-course-created.png"),fullPage:true});
});
