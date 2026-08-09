# 调度系统（基于 APScheduler 和 SheetCommand）
import logging
from apscheduler.schedulers.qt import QtScheduler

logger = logging.getLogger("sheets_toolkit.scheduler")


class TaskScheduler:
    """
    任务调度管理器，封装 APScheduler 的 QtScheduler。
    支持一次性、间隔、每日三种调度类型，以及暂停/恢复功能。
    """

    def __init__(self):
        self.scheduler = QtScheduler()
        self.scheduler.start()
        logger.info("任务调度器已启动")

    def add_once(self, name, time, command, controller):
        """添加一次性任务"""
        def task():
            controller.run_command(command)
        job = self.scheduler.add_job(task, 'date', id=name, run_date=time)
        logger.info(f"已添加一次性任务: {name}，执行时间: {time}")
        return job

    def add_interval(self, name, seconds, command, controller):
        """添加间隔任务"""
        def task():
            controller.run_command(command)
        job = self.scheduler.add_job(task, 'interval', id=name, seconds=seconds)
        logger.info(f"已添加间隔任务: {name}，间隔: {seconds}秒")
        return job

    def add_daily(self, name, hour, minute, command, controller):
        """添加每日定时任务"""
        def task():
            controller.run_command(command)
        job = self.scheduler.add_job(task, 'cron', id=name, hour=hour, minute=minute)
        logger.info(f"已添加每日任务: {name}，时间: {hour}:{minute:02d}")
        return job

    def pause_job(self, name):
        """暂停指定任务"""
        self.scheduler.pause_job(name)
        logger.info(f"已暂停任务: {name}")

    def resume_job(self, name):
        """恢复指定任务"""
        self.scheduler.resume_job(name)
        logger.info(f"已恢复任务: {name}")

    def remove(self, name):
        """移除指定任务"""
        try:
            self.scheduler.remove_job(name)
            logger.info(f"已移除任务: {name}")
        except Exception as e:
            logger.warning(f"移除任务失败 [{name}]: {e}")

    def get_jobs(self):
        """获取所有已注册的任务列表"""
        return self.scheduler.get_jobs()

    def clear_all(self):
        """清除所有调度任务"""
        self.scheduler.remove_all_jobs()
        logger.info("已清除所有调度任务")

    def shutdown(self):
        """关闭调度器"""
        self.scheduler.shutdown(wait=False)
        logger.info("调度器已关闭")


class ScheduledCommand:
    """
    可调度命令封装类。
    将 Command 和调度参数绑定在一起，便于注册到调度器。
    """
    def __init__(self, name: str, command, schedule_type: str, schedule_args: dict):
        self.name = name
        self.command = command
        self.schedule_type = schedule_type
        self.schedule_args = schedule_args

    def register(self, scheduler, controller):
        """注册到调度器"""
        if self.schedule_type == "once":
            scheduler.add_once(
                self.name, self.schedule_args['run_date'],
                self.command, controller
            )
        elif self.schedule_type == "interval":
            scheduler.add_interval(
                self.name, self.schedule_args['seconds'],
                self.command, controller
            )
        elif self.schedule_type == "daily":
            scheduler.add_daily(
                self.name, self.schedule_args['hour'],
                self.schedule_args['minute'], self.command, controller
            )
        else:
            logger.error(f"未知的调度类型: {self.schedule_type}")
