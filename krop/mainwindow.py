# -*- coding: iso-8859-1 -*-

"""
The main window of krop

Copyright (C) 2010-2025 Armin Straub, http://arminstraub.com
"""

"""
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.
"""

import sys
from datetime import datetime
import json

from krop.qt import *
from krop.config import PYQT6
from pathlib import Path

if PYQT6:
    from krop.mainwindowui_qt6 import Ui_MainWindow
else:
    from krop.mainwindowui_qt5 import Ui_MainWindow

from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QMessageBox, QCheckBox, QLabel

from krop.viewerselections import ViewerSelections, aspectRatioFromStr
from krop.vieweritem import ViewerItem
from krop.pdfcropper import PdfFile, PyMuPdfImageExtractor, PdfEncryptedError
from krop.autotrim import autoTrimMargins

APP_NAME = "Krop"
FILE_NAME = "years_list.txt"

def getYearsFilePath():
    data_dir = Path.home() / APP_NAME
    data_dir.mkdir(exist_ok=True)
    return data_dir / FILE_NAME

def addYearToList(years: list[str]):
    file_path = getYearsFilePath()

    with file_path.open(mode="a", encoding="utf-8") as f:
        for year in years:
            f.write(f"{year}\n")

def getYearsList() -> list:
    file_path = getYearsFilePath()
    if not file_path.exists():
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
        return sorted({int(y) for y in content.splitlines() if y.strip()})
    except (ValueError, OSError):
        return []

def getBookYear(full_name):
    stem = Path(full_name).stem
    return int(stem[-4:])

def getTimestampedName():
    now = datetime.now()
    dt_string = now.strftime("%Y-%m-%d %H-%M-%S")
    return f"Image {dt_string}.png"

class AspectRatioType:
    def __init__(self, name, width, height):
        self.name = name
        self.width = width
        self.height = height

class AspectRatioTypeManager:

    def __init__(self):
        self.types = []
        self.defaultsUsed = False

    def __iter__(self):
        return iter(self.types)

    def addType(self, name, width, height):
        self.types.append(AspectRatioType(name, width, height))

    def getType(self, index):
        if index >= len(self.types):
            return None
        return self.types[index]

    def addDefaults(self):
        pass

    def settingsCaption(self):
        pass
  
    def saveTypes(self, settings):
        c = self.settingsCaption()
        # if the defaults have been used, we still write them to the config
        # file, making it easier for the user to edit/add, but we append
        # Defaults to the caption so that these get automatically overriden by
        # future versions of krop (which may have updated defaults)
        if self.defaultsUsed:
            c += "Defaults"
        settings.beginWriteArray(c)
        for i in range(len(self.types)):
            t = self.types[i]
            settings.setArrayIndex(i)
            settings.setValue("Name", t.name)
            settings.setValue("Width", t.width)
            settings.setValue("Height", t.height)
        settings.endArray()
  
    def loadTypes(self, settings):
        count = settings.beginReadArray(self.settingsCaption())
        for i in range(count):
            settings.setArrayIndex(i)
            name = settings.value("Name")
            width = float(settings.value("Width"))
            height = float(settings.value("Height"))
            self.addType(name, width, height)
        settings.endArray()
        if count==0:
            self.defaultsUsed = True
            self.addDefaults()

class SelAspectRatioTypeManager(AspectRatioTypeManager):

    def settingsCaption(self):
        return "SelAspectRatios"

    def addDefaults(self):
        self.addType("Flexible aspect ratio", 0, 0)
        self.addType("A4/A5 etc.", 1, 1.414)
        self.addType("A4/A5 etc. (landscape)", 1.414, 1)
        self.addType("Letter", 8.5, 11)
        self.addType("Letter (landscape)", 11, 8.5)
        self.addType("Legal", 8.5, 14)
        self.addType("Legal (landscape)", 14, 8.5)

class DeviceTypeManager(AspectRatioTypeManager):

    def settingsCaption(self):
        return "DeviceTypes"

    def addDefaults(self):
        self.addType("No fitting", 0, 0)
        self.addType("4:3 eReader", 4, 3)
        self.addType("4:3 eReader (widescreen)", 3, 4)
        self.addType("Nook 1st Ed.", 600, 730)
        self.addType("Nook 1st Ed. (widescreen)", 730, 600)


class MainWindow(QMainWindow):

    fileName = None

    def __init__(self):
        QMainWindow.__init__(self)

        self.selAspectRatioTypes = SelAspectRatioTypeManager()
        self.deviceTypes = DeviceTypeManager()

        self._viewer = ViewerItem(self)

        self.ui=Ui_MainWindow()
        self.ui.setupUi(self)

        self.setAcceptDrops(True)

        # self.ui.tabWidget.

        # http://standards.freedesktop.org/icon-naming-spec/icon-naming-spec-latest.html
        self.setWindowIcon(QIcon.fromTheme('edit-cut'))
        self.ui.actionOpenFile.setIcon(QIcon.fromTheme('document-open'))
        self.ui.actionKrop.setIcon(QIcon.fromTheme('face-smile'))
        self.ui.actionZoomIn.setIcon(QIcon.fromTheme('zoom-in'))
        self.ui.actionZoomOut.setIcon(QIcon.fromTheme('zoom-out'))
        self.ui.actionFitInView.setIcon(QIcon.fromTheme('zoom-fit-best'))
        self.ui.actionPreviousPage.setIcon(QIcon.fromTheme('go-previous'))
        self.ui.actionNextPage.setIcon(QIcon.fromTheme('go-next'))
        self.ui.actionFirstPage.setIcon(QIcon.fromTheme('go-first'))
        self.ui.actionLastPage.setIcon(QIcon.fromTheme('go-last'))
        self.ui.actionPreviousPDF.setIcon(QIcon.fromTheme('media-skip-backward'))
        self.ui.actionNextPDF.setIcon(QIcon.fromTheme('media-skip-forward'))
        self.ui.actionTrimMargins.setIcon(QIcon.fromTheme('transform-crop'))
        self.ui.actionTrimMarginsAll.setIcon(QIcon.fromTheme('transform-crop'))
        # self.ui.actionTrimMarginsAll.setIcon(QIcon.fromTheme('select-rectangular'))
        # self.ui.actionTrimMarginsAll.setIcon(QIcon.fromTheme('edit-guides'))
        self.ui.actionNewSelection.setIcon(QIcon.fromTheme('select-rectangular'))
        # self.ui.actionNewSelection.setIcon(QIcon.fromTheme('draw-rectangle'))
        self.ui.actionDeleteSelection.setIcon(QIcon.fromTheme('edit-delete'))

        if QIcon.hasThemeIcon('document-open'):
            self.ui.buttonFileSelect.setIcon(QIcon.fromTheme('document-open'))
        else:
            self.ui.buttonFileSelect.setText('...')
            self.ui.buttonFileSelect.setAutoRaise(False)

        if QIcon.hasThemeIcon('go-first') and QIcon.hasThemeIcon('go-previous') \
                and QIcon.hasThemeIcon('go-next') and QIcon.hasThemeIcon('go-last'):
            self.ui.buttonFirst.setIcon(QIcon.fromTheme('go-first'))
            self.ui.buttonPrevious.setIcon(QIcon.fromTheme('go-previous'))
            self.ui.buttonNext.setIcon(QIcon.fromTheme('go-next'))
            self.ui.buttonLast.setIcon(QIcon.fromTheme('go-last'))
        else:
            self.ui.buttonFirst.setText('<<')
            self.ui.buttonPrevious.setText('<')
            self.ui.buttonNext.setText('>')
            self.ui.buttonLast.setText('>>')
            self.ui.buttonFirst.setFlat(False)
            self.ui.buttonPrevious.setFlat(False)
            self.ui.buttonNext.setFlat(False)
            self.ui.buttonLast.setFlat(False)

        # we need to add the action to a widget in order for keyboard shortcuts to work
        self.addAction(self.ui.actionNewSelection)
        self.addAction(self.ui.actionNewSelectionGrid)
        self.addAction(self.ui.actionDeleteSelection)
        self.addAction(self.ui.actionFirstPage)
        self.addAction(self.ui.actionLastPage)

        self.ui.actionOpenFile.triggered.connect(self.slotOpenFile)
        self.ui.actionSelectFile.triggered.connect(self.slotSelectFile)
        self.ui.actionKrop.triggered.connect(self.slotKrop)
        self.ui.actionZoomIn.triggered.connect(self.slotZoomIn)
        self.ui.actionZoomOut.triggered.connect(self.slotZoomOut)
        self.ui.actionFitInView.toggled.connect(self.slotFitInView)
        self.ui.actionPreviousPage.triggered.connect(self.slotPreviousPage)
        self.ui.actionNextPage.triggered.connect(self.slotNextPage)
        self.ui.actionFirstPage.triggered.connect(self.slotFirstPage)
        self.ui.actionLastPage.triggered.connect(self.slotLastPage)
        self.ui.actionPreviousPDF.triggered.connect(self.slotPreviousPDF)
        self.ui.actionNextPDF.triggered.connect(self.slotNextPDF)
        self.ui.actionDeleteSelection.triggered.connect(self.slotDeleteSelection)
        self.ui.actionNewSelection.triggered.connect(self.slotNewSelection)
        self.ui.actionNewSelectionGrid.triggered.connect(self.slotNewSelectionGrid)
        self.ui.actionTrimMargins.triggered.connect(self.slotTrimMargins)
        self.ui.actionTrimMarginsAll.triggered.connect(self.slotTrimMarginsAll)
        self.ui.documentView.customContextMenuRequested.connect(self.slotContextMenu)
        self.ui.editCurrentPage.textEdited.connect(self.slotCurrentPageEdited)
        self.ui.splitter.splitterMoved.connect(self.slotSplitterMoved)

        self.ui.buttonGenerateYearList.clicked.connect(self.slotGenerateYearList)
        self.ui.buttonResetYears.clicked.connect(self.slotClearList)

        self.pdfScene = QGraphicsScene(self.ui.documentView)
        self.pdfScene.setBackgroundBrush(self.pdfScene.palette().dark())
        self.pdfScene.addItem(self.viewer)

        self.readSettings()
        self.refreshYearList()

        self.ui.documentView.setScene(self.pdfScene)
        self.ui.documentView.setFocus()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith('.pdf'):
                self.openFile(file_path)

    @property
    def viewer(self):
        return self._viewer

    @property
    def selections(self):
        return self.viewer.selections

    def currentSelectionUpdated(self):
        pass

    def readSettings(self):
        settings = QSettings()
        geometry = settings.value("Window/Geometry", "")
        if geometry:
            self.restoreGeometry(geometry)
        splitter = settings.value("Window/Splitter", "")
        if splitter:
            self.ui.splitter.restoreState(splitter)
        self.ui.actionFitInView.setChecked(settings.value("Window/FitInView", "") == "true")

        self.ui.editInitials.setText(settings.value("Other/Initials", ""))
        self.ui.editFile.setText(settings.value("Save/Folder", ""))

        self.selAspectRatioTypes.loadTypes(settings)
        self.deviceTypes.loadTypes(settings)

    def writeSettings(self):
        settings = QSettings()
        settings.setValue("Window/Geometry", self.saveGeometry())
        settings.setValue("Window/Splitter", self.ui.splitter.saveState())
        settings.setValue("Window/FitInView", "true" if
                self.ui.actionFitInView.isChecked() else "false")

        settings.setValue("Other/Initials", self.ui.editInitials.text())
        settings.setValue("Save/Folder", self.ui.editFile.text())

        self.selAspectRatioTypes.saveTypes(settings)
        self.deviceTypes.saveTypes(settings)

    def openFile(self, fileName):
        if fileName:
            self.viewer.load(fileName)
            if not self.viewer.isEmpty():
                self.fileName = fileName
                self.slotFitInView(self.ui.actionFitInView.isChecked())
            else:
                self.fileName = ''
                self.showWarning(self.tr("Something got in our way"),
                        self.tr("The PDF file couldn't be read. "
                            "Please check the file and its permissions."))
            self.setWindowFilePath(self.fileName)
            self.ui.actionKrop.setEnabled(not self.viewer.isEmpty())
            self.ui.actionTrimMarginsAll.setEnabled(not self.viewer.isEmpty())
            self.updateControls()
            self.ui.editLastFiscalYear.setValue(getBookYear(self.fileName) - 1)
            self.refreshYearList()

    def clearListUI(self):
        while self.ui.layoutYears.count():
            item = self.ui.layoutYears.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refreshYearList(self):
        self.clearListUI()

        years_list = getYearsList()
        if not years_list:
            return

        min_year = min(years_list)
        max_year = max(years_list)
        all_years = range(min_year, max_year + 1)

        for year in all_years:
            label = QLabel(str(year))

            color = "black" if year in years_list else "red"
            label.setStyleSheet(f"color: {color}; font-family: Arial; font-size: 12pt;")

            self.ui.layoutYears.addWidget(label)

    def slotClearList(self):
        self.clearListUI()
        file_path = getYearsFilePath()
        file_path.write_text("", encoding="utf-8")

    def slotOpenFile(self):
        fileName = QFileDialog.getOpenFileName(self,
             self.tr("Open PDF"), "", self.tr("PDF Files (*.pdf)"));
        fileName = fileName[0]
        self.openFile(fileName)

    def slotSelectFile(self):
        dirPath = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Folder to Save Screenshots"),
            "",
            QFileDialog.Option.ShowDirsOnly
        )

        if dirPath:
            self.ui.editFile.setText(dirPath)

    def showWarning(self, title, text):
        # if krop is called with parameter --go, then the main window is never
        # shown; in that case, we output the warning to the shell
        if self.isVisible():
            QMessageBox.warning(self, title, text)
        else:
            sys.stderr.write(self.tr('WARNING: ') + title + '\n' + text + '\n')

    def str2pages(self, s):
        pages = []
        intervals = [ [ n.strip() for n in i.split('-') ]
                for i in s.split(',') ]
        for i in intervals:
            a,b = i[0], i[-1]
            if a:
                if a == 'current':
                    a = self.viewer.currentPageIndex + 1
                if b == 'current':
                    b = self.viewer.currentPageIndex + 1
                if not b: b = self.viewer.numPages()
                pages.extend(range(int(a)-1,int(b))) # subtract 1 because pages are counted from 0 internally
        return pages

    def getScreenshotsPath(self):
        path = Path(self.ui.editFile.text().strip())

        if path.is_dir():
            return path
        return path.parent

    def slotKrop(self):
        # file names
        inputFileName = self.fileName
        outputFileName = self.getScreenshotsPath() / Path(self.fileName).stem / getTimestampedName()
        outputFileName.parent.mkdir(parents=True, exist_ok=True)

        self.saveData(outputFileName.parent)

        pages = range(self.viewer.numPages())

        rotation = [0, 270, 90, 180][0]

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pdf = PdfFile()
            pdf.loadFromFile(inputFileName)
            cropper = PyMuPdfImageExtractor()
            cropper.copyDocumentRoot(pdf)
            for pageIdx in pages:
                c = self.viewer.cropValues(pageIdx)
                if c:
                    cropper.addPageCropped(pdf, pageIdx, c, rotation)
            cropper.writeToFile(outputFileName)
            QApplication.restoreOverrideCursor()

        except PdfEncryptedError as err:
            QApplication.restoreOverrideCursor()
            self.showWarning(self.tr("PDF is encrypted"),
                    self.tr("This PDF needs to be decrypted before cropping. "
                        "You could try to do that using qpdf:"
                        "\nqpdf --password='hello' --decrypt encrypted.pdf decrypted.pdf"))
            raise err
        except IOError as err:
            QApplication.restoreOverrideCursor()
            self.showWarning(self.tr("Could not write cropped PDF"),
                    self.tr("An error occured while writing the cropped PDF. "
                        "Please make sure that you have permission to write to "
                        "the selected file."
                        "\n\nThe official error is:\n\n{0}").format(err))
        except Exception as err:
            QApplication.restoreOverrideCursor()
            self.showWarning(self.tr("Something got in our way"),
                    self.tr("The following unexpected error has occured:"
                    "\n\n{0}").format(err))
            raise err

        self.selections.deleteSelections()

    def slotGenerateYearList(self):
        while self.ui.layoutYearList.count() > 1: # > 1 to keep the spacer at the bottom
            item = self.ui.layoutYearList.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.year_checkboxes = {}

        try:
            start = self.ui.editFirstFiscalYear.value()
            end = self.ui.editLastFiscalYear.value()

            if start > end:
                start, end = end, start

            # Assuming get_years_list() is defined elsewhere in your logic
            years_list = getYearsList()

            for year in range(start, end + 1):
                # Create the checkbox
                chk = QCheckBox(str(year))

                # Set initial state (True if NOT in years_list, matching your Tkinter logic)
                initial_state = year not in years_list
                chk.setChecked(initial_state)

                # 3. Add to the layout (inserting above the spacer)
                self.ui.layoutYearList.insertWidget(self.ui.layoutYearList.count() - 1, chk)

                # Store reference to the checkbox object
                self.year_checkboxes[year] = chk

        except Exception as e:
            # PyQt equivalent of messagebox.showerror
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

    def saveData(self, outputPath):

        # Prepare data
        selected_years = [year for year, chk in self.year_checkboxes.items() if chk.isChecked()]

        data = {
            "quality": self.ui.comboQuality.currentText(),
            "first_fiscal_year": self.ui.editFirstFiscalYear.value(),
            "last_fiscal_year": self.ui.editLastFiscalYear.value(),
            "selected_fiscal_years": selected_years,
            "ra": self.ui.editInitials.text()
        }

        # Save to JSON
        json_path = outputPath / "dict.json"
        with open(json_path, "w") as f:
            json.dump(data, f, indent=4)

        addYearToList(selected_years)

    def slotZoomIn(self):
        self.ui.actionFitInView.setChecked(False)
        self.ui.documentView.scale(1.2, 1.2)

    def slotZoomOut(self):
        self.ui.actionFitInView.setChecked(False)
        self.ui.documentView.scale(1/1.2, 1/1.2)

    def slotFitInView(self, checked):
        if checked:
            self.ui.documentView.fitInView(self.pdfScene.sceneRect(),
                    Qt.AspectRatioMode.KeepAspectRatio)

    def slotSplitterMoved(self, pos, idx):
        self.slotFitInView(self.ui.actionFitInView.isChecked())

    def slotPreviousPage(self):
        self.viewer.previousPage()
        self.updateControls()

    def slotNextPage(self):
        self.viewer.nextPage()
        self.updateControls()

    def slotFirstPage(self):
        self.viewer.firstPage()
        self.updateControls()

    def slotLastPage(self):
        self.viewer.lastPage()
        self.updateControls()

    def slotPreviousPDF(self):
        current_path = Path(self.fileName).resolve()
        directory = current_path.parent

        all_files = sorted(
            [f for f in directory.iterdir() if f.suffix.lower() == '.pdf'],
            key=lambda x: x.name.lower()
        )

        try:
            current_index = all_files.index(current_path)
        except ValueError:
            # This handles cases where the file might have been moved or renamed
            print("Current file not found in directory.")
            return

        next_index = (current_index - 1) % len(all_files)
        next_file = all_files[next_index]

        self.openFile(str(next_file))

    def slotNextPDF(self):
        current_path = Path(self.fileName).resolve()
        directory = current_path.parent

        all_files = sorted(
            [f for f in directory.iterdir() if f.suffix.lower() == '.pdf'],
            key=lambda x: x.name.lower()
        )

        try:
            current_index = all_files.index(current_path)
        except ValueError:
            # This handles cases where the file might have been moved or renamed
            print("Current file not found in directory.")
            return

        next_index = (current_index + 1) % len(all_files)
        next_file = all_files[next_index]

        self.openFile(str(next_file))

    def slotCurrentPageEdited(self, text):
        try:
            n = int(text)
            self.viewer.currentPageIndex = n-1
            self.updateControls()
        except ValueError:
            pass

    def updateControls(self):
        cur = ''
        num = ''
        if not self.viewer.isEmpty():
            cur = str(self.viewer.currentPageIndex+1)
            num = str(self.viewer.numPages())
        self.ui.editCurrentPage.setText(cur)
        self.ui.editMaxPage.setText(num)

    def slotContextMenu(self, pos):
        if self.viewer.isEmpty():
            return

        item = self.ui.documentView.itemAt(pos)
        menuForSelection = False
        try:
            self.selections.currentSelection = item.selection
            menuForSelection = True
        except AttributeError:
            pass
        popMenu = QMenu()
        popMenu.addAction(self.ui.actionNewSelection)
        popMenu.addAction(self.ui.actionNewSelectionGrid)
        if menuForSelection:
            popMenu.addAction(self.ui.actionDeleteSelection)
            popMenu.addAction(self.ui.actionTrimMargins)
        else:
            popMenu.addAction(self.ui.actionTrimMarginsAll)
        popMenu.exec(self.ui.documentView.mapToGlobal(pos))

    def slotDeleteSelection(self):
        if self.selections.currentSelection is not None:
            self.selections.deleteSelection(self.selections.currentSelection)

    def slotNewSelection(self):
        self.createSelectionGrid("1")

    def slotNewSelectionGrid(self):
        if not self.viewer.isEmpty():
            default = "2x1"
            if self.viewer.isPortrait():
                default = "1x2"
            grid, ok = QInputDialog.getText(self, self.tr('New Selection Grid...'),
                    self.tr('Enter the dimensions of the grid:'), text=default)
            if ok:
                self.createSelectionGrid(grid)

    def createSelectionGrid(self, grid):
        if self.viewer.isEmpty():
            return

        try:
            colsrows = [int(x) for x in grid.split('x')]
            cols = colsrows[0]
            # if only one value is specified, we determine the number of
            # columns/rows according to whether the page is landscape or
            # portrait
            if len(colsrows) == 1:
                if self.viewer.isPortrait():
                    cols, rows = 1, cols
                else:
                    rows = 1
            else:
                rows = colsrows[1]
        except:
            self.showWarning(self.tr("Bad value for grid parameter"), self.tr("For creating a grid "
                "of selections, you need to specify the dimensions of the grid in the form '2x3'. "
                "You can also enter a single number, in which case the number of columns/rows is "
                "determined according to whether the page is landscape or portrait."))
            return

        for j in range(rows):
            for i in range(cols):
                sel = self.selections.addSelection()
                r = sel.boundingRect()
                w = r.width()/cols
                h = r.height()/rows
                p0 = QPointF(r.left()+i*w, r.top()+j*h)
                sel.setBoundingRect(p0, p0 + QPointF(w, h))
        self.pdfScene.update()

    def getPadding(self):
        """Return [top, right, bottom, left] tuple specifying padding for trimming margins."""
        try:
            # padding can be specified as in CSS (using one to four values):
            # top, right, bottom, left
            # top, right+left, bottom
            # top+bottom, right+left
            # top+bottom+right+left
            padding = [ float(a) for a in self.ui.editPadding.text().split(',') if a ]
            if len(padding) == 0:
                return [0,0,0,0]
            if len(padding) == 1:
                return 4*padding
            if len(padding) == 2:
                return 2*padding
            if len(padding) == 3:
                return padding + [padding[1]]
            if len(padding) == 4:
                return padding
            raise ValueError
        except ValueError:
            self.showWarning(self.tr("Bad value for padding"), self.tr("The value of padding "
                "(under settings for trimming margins) must be a list of one to four floats, "
                "separated by a comma."
                "\n\nAs in CSS, options are: "
                "\n(four values) top, right, bottom, left"
                "\n(three values) top, right+left, bottom"
                "\n(two values) top+bottom, right+left"))
            return [0,0,0,0]

    def slotTrimMarginsAll(self):
        # trim margins of all selections on the current page
        noSelections = True
        for sel in self.selections.items:
            if sel.isVisible():
                noSelections = False
                self.trimMarginsSelection(sel)
        # if there is no selections, then create one
        if noSelections and not self.viewer.isEmpty():
            sel = self.selections.addSelection()
            self.trimMarginsSelection(sel)
        self.pdfScene.update()

    def slotTrimMargins(self):
        if self.selections.currentSelection is not None:
            self.trimMarginsSelection(self.selections.currentSelection)
            self.pdfScene.update()

    def trimMarginsSelection(self, sel):
        sensitivity = float(self.ui.editSensitivity.text())
        allowedchanges = float(self.ui.editAllowedChanges.text())

        # if requested, use all pages for trimming; otherwise, just the current page
        pages = [self.viewer.currentPageIndex]
        if self.ui.checkTrimUseAllPages.isChecked():
            pages = [i for i in range(self.viewer.numPages()) if sel.selectionVisibleOnPage(i)]

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # orect is the original selection, nrect is the trimmed version
            orect = sel.mapRectToImage(sel.rect).toRect()
            nrect = None
            for idx in pages:
                # calculate values for trimming
                img = self.viewer.getImage(idx)
                nrect = autoTrimMargins(img, orect, nrect, sensitivity, allowedchanges)

            orect = QRectF(orect)
            nrect = QRectF(nrect)

            # adjust for padding ...
            dtop, dright, dbottom, dleft = self.getPadding()
            nrect.adjust(-dleft, -dtop, dright, dbottom)
            # ... but don't overadjust
            nrect = nrect.intersected(orect)

            # take fixed aspect ratio into account
            if sel.aspectRatio:
                r, w, h = sel.aspectRatio, nrect.width(), nrect.height()
                nw, nh = max(w, h*r), max(h, w/r)
                if nw > w:
                    d1 = (nw - w) / 2
                    if nrect.left() - orect.left() < d1:
                        d1 = nrect.left() - orect.left()
                    elif orect.right() - nrect.right() < d1:
                        d1 = nw - w - orect.right() + nrect.right()
                    d2 = nw - w - d1
                    nrect.adjust(-d1, 0, d2, 0)
                elif nh > h:
                    d1 = (nh - h) / 2
                    if nrect.top() - orect.top() < d1:
                        d1 = nrect.top() - orect.top()
                    elif orect.bottom() - nrect.bottom() < d1:
                        d1 = nh - h - orect.bottom() + nrect.bottom()
                    d2 = nh - h - d1
                    nrect.adjust(0, -d1, 0, d2)

            # set selection to new values
            nrect = sel.mapRectFromImage(nrect)
            sel.setBoundingRect(nrect.topLeft(), nrect.bottomRight())
        finally:
            QApplication.restoreOverrideCursor()

    def resizeEvent(self, event):
        self.slotFitInView(self.ui.actionFitInView.isChecked())

    def closeEvent(self, event):
        self.writeSettings()
