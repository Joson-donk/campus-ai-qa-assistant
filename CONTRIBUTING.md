# 代码提交与评审流程

main 分支受保护：不能直接推送，所有改动都要通过 Pull Request（PR），并且至少 1 名组员审核通过后才能合并。

## 一、提交改动（作者）
1. 同步最新代码：`git checkout main`，`git pull`
2. 新建自己的分支：`git checkout -b 模块号-简短说明`，例如 `03-add-chat-api`
3. 只在自己负责的模块文件夹里改动，提交：`git add .`，`git commit -m "说明改了什么"`
4. 推送分支：`git push -u origin 分支名`
5. 在 GitHub 页面点 **Compare & pull request**，按模板填写，右侧 **Reviewers** 选 1 名组员
6. 评审提出修改意见后，在同一分支继续提交并推送，PR 会自动更新

## 二、评审（审核人）
打开 PR，进入 **Files changed** 逐个文件看，重点检查：
- 功能：是否实现了 PR 描述的内容，有没有明显 bug
- 范围：是否只改了本模块，没误删、误改别人的文件
- 规范：命名清楚、有必要注释，没有调试残留代码
- 安全：没有密钥、密码、个人信息、大文件、压缩包
- 测试：涉及后端逻辑时，测试能通过

看完点 **Review changes**，选择：
- **Approve**：没问题，同意合并
- **Request changes**：需要修改，并写明具体意见（可以在代码行上直接评论）
- **Comment**：只提问题或建议

## 三、合并
- 获得 1 个 Approve 且没有未处理的修改意见后，由作者点 **Merge pull request** 合并
- 合并后可删除该分支，本地执行 `git checkout main`，`git pull`

## 约定
- 一个 PR 只做一件事，尽量小，方便评审
- 评审尽量在 24 小时内完成
- 不要审核通过自己的 PR