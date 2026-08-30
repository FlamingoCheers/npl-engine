from .rules import STYLE_PRESETS, get_style, resolve_style

# features / fingerprint 按需导入（fingerprint 依赖 features 注册表，
# 保持惰性可让第三方只注册特征而跳过词表加载）
