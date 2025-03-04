# Dream-Moments-Dify

简体中文 · [English](./README_EN.md) 

My-Dream-Moments (集成 Dify 的增强版-易水哲)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

   🚀 **My-Dream-Moments** 是一个基于 LLM（大语言模型）的情感陪伴程序，支持微信（WeChat），提供更真实的情感交互体验。 

​		本项目在 [KouriChat/KouriChat](https://github.com/KouriChat/KouriChat) 基础上进行了以下修改： 

## ⚡ 一些东西

- **Dify 平台对接**：支持 Dify 作为大语言模型的后端，使 AI 响应更智能、更可控，dify平台地址：https://cloud.dify.ai/
- **机器人唤醒优化**：修复电脑端微信@机器人无法触发的问题，增加机器人名字开头唤醒的功能。
- 极少数情况可能出现回复不完整（已修复）。
- 消息处理队列极少数情况可能出现自我递归死循环。（已修复）

##  **🎨 未来要做** 

- 更新到某个稳定版后，将不再更新。

## ✨ 功能特性 

- **微信机器人集成**：可与微信好友、群聊进行自然交流。 
- **多轮对话支持**：更智能的对话管理，提供连贯的交流体验。 -
- **Dify 平台支持**：可切换至 Dify 作为 AI 引擎，支持自定义 Prompt 及模型配置。 
- **角色扮演模式**：沉浸式交流，支持个性化设定。 

## 📦 一些说明 

- 模型角色使用于dify平台的prompts。
- 模型的温度等参数可以在dify平台设置。
- 未修改更新代码，请不要自动更新。

## 使用示例：

个人私聊触发：

![solo](doc/img/solo.png)

群聊@触发：

![png1](doc/img/png1.png)

群聊开头触发：

![png2](doc/img/png2.png)

## 📌 安装 & 运行

### 1. 前期准备

1. **备用手机/安卓模拟器**  

   微信电脑端登录必须有一个移动设备同时登录，因此不能使用您的主要设备。

2. **微信小号**  

   可以登录微信电脑版即可。

3. **DeepSeek API Key**  

   推荐使用：[获取 API Key（15元免费额度）](https://cloud.siliconflow.cn/i/aQXU6eC5)

4. **Dify API Key**

   https://cloud.dify.ai/

5. **修改Dify应用的提示词**

   无论模型是什么，需要加入以下内容，意思相近即可，其中两个\可以自定，用来设定AI回复几句话：

   ```
   注意：每次对话都要加\来分割对话，每次最多用两个\，最少可以不用。
   或者
   使用反斜线\分隔句子或短语，参考输出示例。模型的输出不应该带时间。
   注意：每次最多用两个\。
   输出示例
   这个电影很好看呢，你喜欢吗？\这个问题的核心在于算法优化，可以从时间复杂度和空间复杂度两个角度分析……\你是不是偷偷学了我的爱好？\嗯？你是不是想考验我的逻辑？\嗯\我也是需要吃饭的\提拉米苏蛮好吃的\但好吃就是高兴呢！\这个问题需要分三步解决哦~\你在看奇怪的东西呢\你在说奇奇怪怪的东西
   ```

### 2. 部署项目

####  1️⃣ 克隆仓库 

```bash
git clone https://github.com/yishuizhe/Dream-Moments-Dify.git 
cd My-Dream-Moments-Dify
```
一键启动

现原项目支持一键启动部署：

run.bat即可

手动如下：
#### 2️⃣ 安装依赖

```bash
pip install -r requirements.txt
```

#### 3️⃣  运行项目

```bash
python run.py
```

原项目有问题可加群：715616260 

- 部署项目推荐使用Windows服务器，[雨云优惠通道注册送首月五折券](https://www.rainyun.com/MzE0MTU=_) 
- 获取 DeepSeek API Key，[获取 API Key（15元免费额度）](https://cloud.siliconflow.cn/i/aQXU6eC5)

---

### 3. 如何使用

- **使用微信小号登录微信电脑版**

- **项目运行后，控制台提示**

  ```bash
  初始化成功，获取到已登录窗口：<您的微信昵称>
  开始运行BOT...
  ```

  即可开始监听并调用模型自动回复消息。

## 声明

- 本项目仅用于交流学习，LLM发言不代表作者本人立场。prompt所模仿角色版权归属原作者。任何未经许可进行的限制级行为均由使用者个人承担。

## 📜 许可证

本项目基于 **GPL v3 许可证**，请遵守开源协议。
**原项目：[KouriChat/KouriChat](https://github.com/KouriChat/KouriChat)**
如果本项目对你有所帮助，欢迎 Star⭐ 支持！

## 🙌 致谢

感谢 [KouriChat](https://github.com/KouriChat/) 提供原始项目，本项目在其基础上进行了功能增强与优化。
如果你有任何问题或建议，欢迎提交 Issue 或 Pull Request！

## **免责声明【必读】**

- 本项目仅供学习和技术研究使用，不得用于任何商业或非法行为，否则后果自负。
- 本项目的作者不对本工具的安全性、完整性、可靠性、有效性、正确性或适用性做任何明示或暗示的保证，也不对本工具的使用或滥用造成的任何直接或间接的损失、责任、索赔、要求或诉讼承担任何责任。
- 本项目的作者保留随时修改、更新、删除或终止本工具的权利，无需事先通知或承担任何义务。
- 本项目的使用者应遵守相关法律法规，尊重微信的版权和隐私，不得侵犯微信或其他第三方的合法权益，不得从事任何违法或不道德的行为。
- 本项目的使用者在下载、安装、运行或使用本工具时，即表示已阅读并同意本免责声明。如有异议，请立即停止使用本工具，并删除所有相关文件。
- 本项目提供的微信接入方式均来自其他开源项目，仅供学习和技术研究使用。

