- - # Dream-Moments-Dify
  
    English · [简体中文](./README.md) 
  
    My-Dream-Moments (Enhanced version integrated with Dify - Yishuizhe)
  
    [![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
  
    🚀 **My-Dream-Moments** is an emotional companionship program based on LLM (Large Language Model), supporting WeChat and providing a more realistic emotional interaction experience.
  
    This project is based on [KouriChat/KouriChat](https://github.com/KouriChat/KouriChat) with the following modifications:
  
    ## ⚡ Features
  
    - **Dify platform integration**: Supports Dify as the backend for the large language model, making AI responses more intelligent and controllable. Dify platform: https://cloud.dify.ai/
    - **Bot wake-up optimization**: Fixes the issue where the bot could not be triggered on the desktop version of WeChat when @mentioned. Also adds functionality to wake up the bot by starting messages with its name.
    - Extremely rare cases of incomplete responses (fixed).
    - Extremely rare cases where the message processing queue might cause a self-recursive infinite loop (fixed).
  
    ## 🎨 Future Plans
  
    - After updating to a stable version, there will be no further updates.
  
    ## ✨ Features
  
    - **WeChat bot integration**: Enables natural conversations with WeChat friends and group chats.
    - **Multi-turn dialogue support**: Provides more intelligent conversation management for a coherent exchange.
    - **Dify platform support**: Allows switching to Dify as the AI engine, supporting custom prompts and model configurations.
    - **Role-playing mode**: Enables immersive interactions with personalized settings.
  
    ## 📦 Additional Notes
  
    - Model roles are used in the prompts of the Dify platform.
    - Model parameters such as temperature can be configured on the Dify platform.
    - If the code has not been modified, do not update it automatically.
  
    ## Usage Examples:
  
    Personal chat trigger:
  
    ![solo](doc/img/solo.png)
  
    Group chat @ trigger:
  
    ![png1](doc/img/png1.png)
  
    Group chat prefix trigger:
  
    ![png2](doc/img/png2.png)
  
    ## 📌 Installation & Running
  
    ### 1. Prerequisites
  
    1. **Backup mobile phone / Android emulator**
  
       The WeChat desktop login requires a mobile device to be logged in simultaneously, so do not use your primary device.
  
    2. **WeChat secondary account**
  
       You only need an account that can log into the WeChat desktop version.
  
    3. **DeepSeek API Key**
  
       Recommended: [Get API Key (15 RMB free credit)](https://cloud.siliconflow.cn/i/aQXU6eC5)
  
    4. **Dify API Key**
  
       https://cloud.dify.ai/
  
    5. **Modify Dify application's prompt**
  
       Regardless of the model, the following instructions should be included (with two `\` characters customizable for controlling AI response length):
  
       ```
       Note: Each dialogue should be separated by `\`. Use up to two `\`, but it is optional.
       Alternatively, use backslashes `\` to separate sentences or phrases, referring to the output example. The model's output should not include timestamps.
       Note: Use up to two `\` at most.
       Output Example:
       This movie is great, do you like it?\ The core of this question lies in algorithm optimization, which can be analyzed from the perspectives of time complexity and space complexity...\ Are you secretly learning my hobbies?\ Hmm? Are you testing my logic?\ Hmm\ I also need to eat\ Tiramisu tastes good\ But delicious means happiness!\ This problem needs to be solved in three steps~\ You are looking at something weird\ You are saying something strange
       ```
  
    ### 2. Deploying the Project
  
    #### 1️⃣ Clone the Repository
  
    ```bash
    git clone https://github.com/yishuizhe/Dream-Moments-Dify.git 
    cd My-Dream-Moments-Dify
    ```
  
    One-click start:
  
    The original project supports one-click deployment:
  
    Run `run.bat` to start.
  
    Manual steps:
  
    #### 2️⃣ Install Dependencies
  
    ```bash
    pip install -r requirements.txt
    ```
  
    #### 3️⃣ Run the Project
  
    ```bash
    python run.py
    ```
  
    If you encounter issues, you can join the group: 715616260
  
    - Deployment is recommended on a Windows server: [Rainyun discount channel (first month half-price)](https://www.rainyun.com/MzE0MTU=_)
    - Get DeepSeek API Key: [Get API Key (15 RMB free credit)](https://cloud.siliconflow.cn/i/aQXU6eC5)
  
    ---
  
    ### 3. How to Use
  
    - **Log into the WeChat desktop version with a secondary account**
  
    - **After running the project, the console will display:**
  
      ```bash
      Initialization successful, logged-in user detected: <Your WeChat Nickname>
      Starting BOT...
      ```
  
      This means it has started listening and will automatically respond to messages.
  
    ## Disclaimer
  
    - This project is for educational and research purposes only. The statements made by the LLM do not represent the views of the author. The prompt-based characters belong to their original creators. Any restricted activities without permission are the sole responsibility of the user.
  
    ## 📜 License
  
    This project is licensed under **GPL v3**. Please comply with open-source agreements.
  
    **Original Project: [KouriChat/KouriChat](https://github.com/KouriChat/KouriChat)**
  
    If this project is helpful to you, consider giving it a Star⭐!
  
    ## 🙌 Acknowledgments
  
    Thanks to [KouriChat](https://github.com/KouriChat/) for providing the original project, upon which this project has been enhanced and optimized.
  
    If you have any questions or suggestions, feel free to submit an Issue or Pull Request!
  
    ## **Disclaimer [Must Read]**
  
    - This project is for educational and technical research purposes only. It must not be used for any commercial or illegal activities. Users are solely responsible for any consequences.
    - The author does not guarantee the security, completeness, reliability, validity, accuracy, or applicability of this tool, nor assumes any liability for direct or indirect losses, claims, or legal actions resulting from its use or misuse.
    - The author reserves the right to modify, update, delete, or terminate this tool at any time without prior notice or obligation.
    - Users must comply with relevant laws and regulations, respect WeChat's copyright and privacy, and must not infringe upon the rights of WeChat or third parties or engage in illegal or unethical behavior.
    - By downloading, installing, running, or using this tool, the user agrees to this disclaimer. If you disagree, please stop using this tool and delete all related files immediately.
    - The WeChat integration methods in this project come from other open-source projects and are for learning and research purposes only.
