# Dream 外部插件目录

Dream 启动时扫描每个直接子目录中的 `dream_plugin.py`：

```text
plugins/
└─ PluginName/
   └─ dream_plugin.py
```

安装 GroupFun：

```powershell
git clone https://github.com/yishuizhe/dow-group-fun.git plugins/GroupFun
Copy-Item plugins\GroupFun\config.json.template plugins\GroupFun\config.json
```

`plugins/*`、插件私人配置和运行数据库默认被 `.gitignore` 排除；只有本说明文件进入 Dream 主仓库。