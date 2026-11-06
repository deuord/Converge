# service/ — 业务层:业务逻辑(sort 规则/错误语义/跨 store 编排)在这层
# 上承路由(协议转换),下调 store(通用 SQL 执行),对齐 Go 的 handler → service → repository
