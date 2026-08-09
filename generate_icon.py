import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QLinearGradient, QPainterPath
from PySide6.QtCore import Qt

def main():
    app = QApplication(sys.argv)
    size = 512
    pixmap = QPixmap(size, size)
    # 【核心】：设置完美的全透明背景，不带任何杂色和锯齿
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    # ================= 1. 绘制底层阴影 =================
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 40))
    painter.drawRoundedRect(64, 74, 384, 384, 80, 80)

    # ================= 2. 绘制翠绿色底层背景 =================
    base_grad = QLinearGradient(64, 64, 448, 448)
    base_grad.setColorAt(0.0, QColor("#0F9D58")) # Google 官方表格绿
    base_grad.setColorAt(1.0, QColor("#34A853"))
    painter.setBrush(base_grad)
    painter.drawRoundedRect(64, 64, 384, 384, 80, 80)

    # ================= 3. 绘制中间的纯白数据表格 =================
    painter.setBrush(QColor(255, 255, 255, 245))
    painter.drawRoundedRect(120, 120, 272, 272, 25, 25)

    # 绘制表格内部分隔线 (绿色)
    pen = QPen(QColor("#0F9D58"), 14, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    
    # 纵线
    painter.drawLine(205, 120, 205, 392)
    # 横线 1
    painter.drawLine(120, 210, 392, 210)
    # 横线 2
    painter.drawLine(120, 300, 392, 300)

    # ================= 4. 右下角绘制 Toolkit 标志 (科技蓝徽章) =================
    # 徽章阴影
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 50))
    painter.drawEllipse(310, 310, 160, 160)
    
    # 徽章渐变底色
    badge_grad = QLinearGradient(310, 310, 470, 470)
    badge_grad.setColorAt(0.0, QColor("#4285F4")) # Google Blue
    badge_grad.setColorAt(1.0, QColor("#1A73E8"))
    painter.setBrush(badge_grad)
    painter.drawEllipse(310, 310, 160, 160)

    # 在徽章中间绘制代表“效率/自动化”的闪电标志
    painter.setBrush(QColor(255, 255, 255))
    bolt = QPainterPath()
    bolt.moveTo(405, 335)
    bolt.lineTo(360, 400)
    bolt.lineTo(395, 400)
    bolt.lineTo(380, 445)
    bolt.lineTo(425, 380)
    bolt.lineTo(390, 380)
    bolt.closeSubpath()
    painter.drawPath(bolt)
    
    painter.end()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    resources_dir = os.path.join(base_dir, "resources")
    if not os.path.exists(resources_dir):
        os.makedirs(resources_dir)
        
    f1 = os.path.join(resources_dir, "main.png")
    f3 = os.path.join(resources_dir, "main.ico")
    
    pixmap.save(f1, "PNG")
    # 生成标准的 Windows ICO 文件用于 EXE 打包
    pixmap.save(f3, "ICO")
    print(f"Absolutely Transparent Background Icons Generated:")
    print(f"- {f1}")
    print(f"- {f3}")

if __name__ == "__main__":
    main()
