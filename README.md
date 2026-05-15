# astrbot_admin_manager

AstrBot 插件管理器，支持插件启停、用户级插件黑名单、使用统计和错误统计。

## 功能

- 启用、停用指定插件
- 记录插件被用户使用的次数和最后使用时间
- 记录插件错误次数、最后错误时间和错误信息
- 设置主人
- 主人可以禁止指定用户使用指定插件

## 安装

将本目录放到 AstrBot 的插件目录：

```text
data/plugins/astrbot_admin_manager
```

然后在 AstrBot WebUI 中重载插件，或重启 AstrBot。

## 首次配置

建议先在 AstrBot WebUI 的插件配置中设置：

- `owner_ids`：主人 QQ 号列表

例如：

```json
["123456789"]
```

如果没有配置主人，插件管理命令不会允许普通用户使用。

也可以开启：

- `allow_first_owner_claim`

开启后，在没有任何主人时，第一个发送以下命令的用户会成为主人：

```text
/apm claim
```

公网机器人不建议开启该选项。

## 命令

所有管理命令都需要主人权限。

### 查看帮助

```text
/apm help
```

### 查看插件列表

```text
/apm plugins
```

### 启用插件

```text
/apm on <插件名>
```

示例：

```text
/apm on example_plugin
```

### 停用插件

```text
/apm off <插件名>
```

示例：

```text
/apm off example_plugin
```

不能通过本插件停用 `astrbot_admin_manager` 自身。

### 禁止用户使用某插件

```text
/apm block <用户ID> <插件名>
```

示例：

```text
/apm block 123456789 example_plugin
```

被禁止后，该用户不能再触发该插件；不影响其他用户使用。

### 解除禁止

```text
/apm unblock <用户ID> <插件名>
```

示例：

```text
/apm unblock 123456789 example_plugin
```

### 查看黑名单

```text
/apm blocks
```

### 查看使用统计

查看全部插件：

```text
/apm stats
```

查看指定插件：

```text
/apm stats <插件名>
```

### 查看错误统计

查看全部插件：

```text
/apm errors
```

查看指定插件：

```text
/apm errors <插件名>
```

### 管理主人

添加主人：

```text
/apm owner add <用户ID>
```

移除主人：

```text
/apm owner remove <用户ID>
```

查看主人列表：

```text
/apm owner list
```

如果主人来自 WebUI 配置 `owner_ids`，需要在 WebUI 配置中移除，不能通过命令移除。

## 数据存储

插件数据保存在 AstrBot 的插件数据目录中：

```text
data/plugin_data/astrbot_admin_manager/data.json
```

包含：

- 动态添加的主人
- 用户插件黑名单
- 插件使用统计
- 插件错误统计

## 说明

用户级黑名单通过高优先级事件处理器实现：当用户触发插件时，本插件会从当前事件的已激活处理器中移除被禁止的插件处理器。

因此它只影响“某个用户是否能使用某个插件”，不会全局停用该插件。
