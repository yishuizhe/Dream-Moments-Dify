# 此文件已经弃用!


# # 用户列表(请配置要和bot说话的账号的昵称或者群名，不要写备注！)
# # 例如：LISTEN_LIST = ['智械危机']
# LISTEN_LIST = ['']
# # DeepSeek API 配置
# # 填你的秘钥
# DEEPSEEK_API_KEY = 'sk-'
# # 硅基流动API注册地址，免费15元额度 https://cloud.siliconflow.cn/i/aQXU6eC5
# DEEPSEEK_BASE_URL = 'https://api.siliconflow.cn/v1/'
# # 如果要使用官方的API
# # DEEPSEEK_BASE_URL = 'https://api.siliconflow.cn/v1/'
# # 如果要使用本地的ai API，把模型和API地址改成本地的
# # DEEPSEEK_BASE_URL = 'https://api.siliconflow.cn/v1/'
# # 硅基流动API的可用赠费的V3模型(deepseek-ai/DeepSeek-V3)，最近会胡言乱语，推荐使用充值才能用的那个Pro，模型名字是(Pro/deepseek-ai/DeepSeek-V3),(Pro/deepseek-ai/DeepSeek-R1)
# # 要切换模型请把括号里的内容复制到MODEL里
# MODEL = 'deepseek-ai/DeepSeek-V3'
# # 官方API的V3模型
# # MODEL = 'deepseek-ai/DeepSeek-V3'
# # 回复最大token
# MAX_TOKEN = 2000
# #温度
# TEMPERATURE = 1.1

# # Moonshot AI配置（用于图片和表情包识别）
# # API申请https://platform.moonshot.cn/console/api-keys （免费15元额度）
# MOONSHOT_API_KEY = 'sk-'
# MOONSHOT_BASE_URL = 'https://api.moonshot.cn/v1'
# MOONSHOT_TEMPERATURE = 1.1

# #图像生成(默认使用 deepseek-ai/Janus-Pro-7B 模型)
# IMAGE_MODEL = 'deepseek-ai/Janus-Pro-7B'
# TEMP_IMAGE_DIR = 'data/images/temp'# 临时图片目录
# #最大的上下文轮数
# MAX_GROUPS = 15
# #prompt文件名
# PROMPT_NAME = 'data/avatars/ATRI/ATRI.md'# prompt文件路径
# #表情包存放目录
# EMOJI_DIR = 'data/avatars/ATRI/emoji'# 表情包目录

# #语音配置（请配置自己的tts服务，用GPT-SoVITS-Inference和自己训练的语音模型）
# TTS_API_URL = 'http://127.0.0.1:5000/tts'
# VOICE_DIR = 'data/voices'# 语音文件目录

# # 自动消息配置
# AUTO_MESSAGE = '请你模拟系统设置的角色，在微信上找对方发消息想知道对方在做什么'
# MIN_COUNTDOWN_HOURS = 1# 最小倒计时时间（小时）
# MAX_COUNTDOWN_HOURS = 3# 最大倒计时时间（小时）

# # 消息发送时间限制
# QUIET_TIME_START = '22:00'# 安静时间开始
# QUIET_TIME_END = '08:00'# 安静时间结束
# #设置记忆保存api，如果需要更改还需在message.py中的init类更改
# MEMORY_API_ENDPOINT = "https://api.siliconflow.cn/v1/"
