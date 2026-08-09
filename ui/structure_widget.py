import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTabWidget, QComboBox, QLineEdit, QCheckBox, QMessageBox
)
from ui.clearable_text_edit import ClearableTextEdit

logger = logging.getLogger("sheets_toolkit.ui.structure")

class SheetManagerPanel(QWidget):
    """表单管理页：批量建表"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        desc = QLabel("💡 <b>批量新建空白表单</b>：输入单据名称列表，系统将为您自动批量创建对应的工作表。")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        layout.addWidget(QLabel("① 键入新生成的工作表名称 (每行一个):"))
        self.names_input = ClearableTextEdit()
        self.names_input.setPlaceholderText("2026-一月报表\n2026-二月报表\n...")
        layout.addWidget(self.names_input)
        
        self.btn_execute = QPushButton("🔨 批量创建工作表")
        self.btn_execute.setObjectName("primary_btn")
        self.btn_execute.clicked.connect(self.execute)
        layout.addWidget(self.btn_execute)
        
        self.status = QLabel("就绪。请输入名称后执行。")
        self.status.setStyleSheet("color: #666;")
        layout.addWidget(self.status)

    def execute(self):
        if not self.controller.is_connected:
            self.status.setText("⚠️ 未连接服务")
            return
            
        names_text = self.names_input.toPlainText()
        names = [n.strip() for n in names_text.split('\n') if n.strip()]
        if not names:
            self.status.setText("⚠️ 请输入至少一个名称")
            return
            
        from services.command.structure_command import BatchCreateSheetsCommand
        try:
            cmd = BatchCreateSheetsCommand(names)
            res = self.controller.run_command(cmd)
            self.status.setText(f"✅ {res}")
            self.names_input.clear()
        except Exception as e:
            self.status.setText(f"❌ 执行失败: {e}")


class ClearRangePanel(QWidget):
    """区域清空页：分离式高阶清理"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        desc = QLabel("💡 <b>高级清理</b>：选定一个范围，您可以选择仅清除数据内容（保留格式和结构），或者仅清除批注内容。")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        form = QHBoxLayout()
        form.addWidget(QLabel("① 数据区域 (例 Sheet1!A1:D10):"))
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("请输入区域表达式...")
        form.addWidget(self.range_input, stretch=1)
        layout.addLayout(form)
        
        opts = QHBoxLayout()
        self.chk_values = QCheckBox("🧹 抹除数据与公式")
        self.chk_values.setChecked(True)
        self.chk_notes = QCheckBox("💬 抹除浮点批注")
        self.chk_notes.setChecked(False)
        opts.addWidget(self.chk_values)
        opts.addWidget(self.chk_notes)
        opts.addStretch()
        layout.addLayout(opts)
        
        self.btn_execute = QPushButton("🧼 执行清理")
        self.btn_execute.setObjectName("danger_btn")
        self.btn_execute.clicked.connect(self.execute)
        layout.addWidget(self.btn_execute)
        
        self.status = QLabel("就绪")
        layout.addWidget(self.status)

    def execute(self):
        if not self.controller.is_connected:
            self.status.setText("⚠️ 未连接服务")
            return
            
        r_str = self.range_input.text().strip()
        if not r_str:
            self.status.setText("⚠️ 必须指定需清空的区域")
            return
            
        if not self.chk_values.isChecked() and not self.chk_notes.isChecked():
            self.status.setText("⚠️ 至少需要勾选一种擦除类型")
            return

        reply = QMessageBox.warning(
            self, "确认清理", 
            f"您确信要擦除 {r_str} 的勾选数据吗？该动作无法撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes: return
            
        from services.command.structure_command import ClearAdvancedCommand
        try:
            cmd = ClearAdvancedCommand(r_str, self.chk_values.isChecked(), self.chk_notes.isChecked())
            res = self.controller.run_command(cmd)
            self.status.setText(f"✅ {res}")
        except Exception as e:
            self.status.setText(f"❌ 执行失败: {e}")


class RowColManagerPanel(QWidget):
    """行与列外科手术操作页"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        desc = QLabel("💡 <b>行列操作</b>：快速在当前工作表中批量插入空行，或者指定区间删除整行（注意：操作应用于当前选中的工作表）。")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # 1. 插行
        insert_box = QHBoxLayout()
        insert_box.addWidget(QLabel("➕ 在第"))
        self.in_insert_idx = QLineEdit()
        self.in_insert_idx.setPlaceholderText("起始行号 (如5)")
        self.in_insert_idx.setMaximumWidth(100)
        insert_box.addWidget(self.in_insert_idx)
        
        insert_box.addWidget(QLabel("行位置处，向下插入"))
        self.in_insert_count = QLineEdit()
        self.in_insert_count.setPlaceholderText("几行 (如10)")
        self.in_insert_count.setMaximumWidth(100)
        insert_box.addWidget(self.in_insert_count)
        
        self.btn_insert = QPushButton("插入空行")
        self.btn_insert.clicked.connect(self.do_insert)
        insert_box.addWidget(self.btn_insert)
        insert_box.addStretch()
        layout.addLayout(insert_box)
        
        # 2. 删行
        del_box = QHBoxLayout()
        del_box.addWidget(QLabel("➖ 批量删除：从第"))
        self.in_del_start = QLineEdit()
        self.in_del_start.setPlaceholderText("起点行号")
        self.in_del_start.setMaximumWidth(80)
        del_box.addWidget(self.in_del_start)
        
        del_box.addWidget(QLabel("行，删至第"))
        self.in_del_end = QLineEdit()
        self.in_del_end.setPlaceholderText("终点行号")
        self.in_del_end.setMaximumWidth(80)
        del_box.addWidget(self.in_del_end)
        
        self.btn_delete = QPushButton("删除选中区间行")
        self.btn_delete.setObjectName("danger_btn")
        self.btn_delete.clicked.connect(self.do_delete)
        del_box.addWidget(self.btn_delete)
        del_box.addStretch()
        layout.addLayout(del_box)

        layout.addStretch()
        
        self.status = QLabel("待机中。所有行列操作基于“1”作为第一行。")
        layout.addWidget(self.status)

    def _get_sheet_id(self):
        sid = self.controller.get_current_sheet_id()
        if sid is None:
            self.status.setText("⚠️ 未能有效锁定底层当前工作表 (请先在左侧正确选择)")
        return sid

    def do_insert(self):
        sid = self._get_sheet_id()
        if sid is None: return
        try:
            start_i = int(self.in_insert_idx.text().strip()) - 1
            num = int(self.in_insert_count.text().strip())
            if start_i < 0 or num <= 0: raise ValueError
            
            from services.command.structure_command import InsertRowsCommand
            cmd = InsertRowsCommand(sid, start_i, num)
            res = self.controller.run_command(cmd)
            self.status.setText(f"✅ {res}")
            
        except ValueError:
            self.status.setText("⚠️ 输入的行号或数量格式错误 (请输入合法的正整数)")
        except Exception as e:
            self.status.setText(f"❌ {e}")

    def do_delete(self):
        sid = self._get_sheet_id()
        if sid is None: return
        try:
            start_i = int(self.in_del_start.text().strip()) - 1
            end_i = int(self.in_del_end.text().strip())
            
            if start_i < 0 or end_i <= start_i: raise ValueError
            
            from services.command.structure_command import DeleteRowsCommand
            cmd = DeleteRowsCommand(sid, start_i, end_i)
            res = self.controller.run_command(cmd)
            self.status.setText(f"✅ {res}")
            
        except ValueError:
            self.status.setText("⚠️ 行号边界错误 (输入格式需: 1起始, 终点应大于起始)")
        except Exception as e:
            self.status.setText(f"❌ {e}")


class StructureWidget(QWidget):
    """全新的表格结构处理中心"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("📄 表格结构管理")
        title.setObjectName("section_title")
        layout.addWidget(title)
        
        self.tabs = QTabWidget()
        
        self.tab_manager = SheetManagerPanel(self.controller, self)
        self.tabs.addTab(self.tab_manager, "➕ 批量创建空表")
        
        self.tab_clear = ClearRangePanel(self.controller, self)
        self.tabs.addTab(self.tab_clear, "🧹 高级区域清除")
        
        self.tab_rowscols = RowColManagerPanel(self.controller, self)
        self.tabs.addTab(self.tab_rowscols, "✂️ 行列批量操作")

        layout.addWidget(self.tabs)
