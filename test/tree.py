import sys
from PyQt5.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem, QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt


class TreeWidgetExample(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
    

    def init_ui(self):
        central_widget = QWidget()
        layout = QVBoxLayout()
        
        # Create QTreeWidget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Name', 'Value'])
        self.tree.setColumnCount(2)
        
        # Add first category
        category1 = QTreeWidgetItem(self.tree, ['Category 1', ''])
        QTreeWidgetItem(category1, ['Attribute 1.1', 'Value 1.1'])
        QTreeWidgetItem(category1, ['Attribute 1.2', 'Value 1.2'])
        QTreeWidgetItem(category1, ['Attribute 1.3', 'Value 1.3'])
        
        # Add second category
        category2 = QTreeWidgetItem(self.tree, ['Category 2', ''])
        QTreeWidgetItem(category2, ['Attribute 2.1', 'Value 2.1'])
        QTreeWidgetItem(category2, ['Attribute 2.2', 'Value 2.2'])
        
        # Add third category
        category3 = QTreeWidgetItem(self.tree, ['Category 3', ''])
        QTreeWidgetItem(category3, ['Attribute 3.1', 'Value 3.1'])
        QTreeWidgetItem(category3, ['Attribute 3.2', 'Value 3.2'])
        QTreeWidgetItem(category3, ['Attribute 3.3', 'Value 3.3'])
        QTreeWidgetItem(category3, ['Attribute 3.4', 'Value 3.4'])
        
        # Set column widths
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 200)
        
        # Expand all items by default
        self.tree.expandAll()
        
        # Add tree to layout
        layout.addWidget(self.tree)
        central_widget.setLayout(layout)
        
        # Set window properties
        self.setCentralWidget(central_widget)
        self.setGeometry(100, 100, 500, 400)
        self.setWindowTitle('QTreeWidget Example')
        self.show()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = TreeWidgetExample()
    sys.exit(app.exec_())