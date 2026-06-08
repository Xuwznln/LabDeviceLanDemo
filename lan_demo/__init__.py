"""LAN demo external device package for Uni-Lab-OS.

跨设备 LAN 闭环（host/slave 分进程）：
  - HubNodeDemo (hub_node_demo): 跨设备 @subscribe 子设备 counter -> 累计满 N 次
    -> call_device_action 走 ros action 终止子设备当前轮；
  - StatusReporterDemo (status_reporter_demo): counter 自增长并周期上报，可被远程终止。

工作站内 hardware_interface 代理（共享串口 / Modbus extra_info）的示例已拆分到独立的
``device_package_workstation_demo`` 包。
"""
