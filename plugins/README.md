# Dream 外部插件目录

Dream 启动时扫描每个直接子目录中的 `dream_plugin.py`：

```text
plugins/
└─ PluginName/
   └─ dream_plugin.py
```

第三方插件、插件配置和运行数据库默认被 `.gitignore` 排除；安装前请自行审阅其代码、许可证和数据处理方式。
