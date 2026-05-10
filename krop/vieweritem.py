"""
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.
"""

# brect is bounding rectangle, represents the total outer boundary of the graphics item.
# irect is image rectangle, represents the internal rectangle where the actual PDF image content is drawn

import sys
from krop.qt import *
from krop.viewerselections import ViewerSelections

class AbstractViewerItem(QGraphicsItem):
    """Abstract class for displaying a PDF document and for allowing the user
    to create selections."""
    def __init__(self, mainwindow):
        QGraphicsItem.__init__(self)
        self.selections = ViewerSelections(self)
        self.reset()
        self.mainwindow = mainwindow

    def reset(self):
        self._currentPageIndex = 0
        self._rotation = 0 # in degrees
        self.brect = QRectF() # QRectF defines a rectangle using floating point precision
        self.irect = QRectF()
        self._images = []
        self.selections.deleteSelections()

    def getRotation(self):
        return self._rotation

    def setRotationAngle(self, angle):
        self._rotation = angle
        self.prepareGeometryChange() # must be called before geometry change

        img = self.getImage(self._currentPageIndex)
        if img:
            # Calculate the new size of the item after rotation
            orig_rect = QRectF(0, 0, img.width(), img.height())
            trans = QTransform().rotate(self._rotation)
            rotated_rect = trans.mapRect(orig_rect) # returns a QRectF that is a copy of the input, mapped into the coordinate system defined by QTransform

            self.brect = rotated_rect
            self.irect = orig_rect # Keep track of original size

            # Center the bounding box on the scene
            self.scene().setSceneRect(self.brect) # scene rectangle is the bounding rectangle of the scene

        self.update()

    rotationAngle = property(getRotation, setRotationAngle)

    def paint(self, painter, option, widget):
        img = self.getImage(self.currentPageIndex)
        if img is None:
            return

        painter.save()
        painter.translate(self.brect.center()) # Translates the coordinate system by the given offset
        painter.rotate(self._rotation) #  Rotate the painter

        draw_rect = QRectF(-self.irect.width()/2, -self.irect.height()/2,
                           self.irect.width(), self.irect.height())

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.drawImage(draw_rect, img) # Draws given image into given rectangle
        painter.restore() # Restores the current painter state, must follow save()

    def mapRectToImage(self, rect):
        # Create a transform that mimics the paint() logic
        # Start with the transformation used in paint
        t = QTransform()
        t.translate(self.brect.center().x(), self.brect.center().y())
        t.rotate(self._rotation)
        t.translate(-self.irect.width()/2, -self.irect.height()/2)

        # Invert it to go from 'Screen/Scene' -> 'Raw Image Pixels'
        inv, success = t.inverted()
        if not success:
            return rect

        # Map the selection polygon (since a rotated rect is a polygon)
        # and get its bounding box in image pixel space
        poly = inv.mapToPolygon(rect.toRect()) # toRect() turn QRectF to QRect
        return poly.boundingRect()

    def mapRectFromImage(self, r):
        return r.translated(self.irect.left(), self.irect.top())

    def boundingRect(self):
        return self.brect

    def isPortrait(self):
        return self.irect.width() <= self.irect.height()

    def getCurrentPageIndex(self):
        return self._currentPageIndex

    def setCurrentPageIndex(self, idx):
        if idx >= self.numPages():
            idx = self.numPages()-1
        if idx < 0:
            idx = 0
        self._currentPageIndex = idx

        img = self.getImage(idx)
        if img is None:
            return

        self.prepareGeometryChange()

        # Original image dimensions
        orig_width = img.width()
        orig_height = img.height()
        self.irect = QRectF(0, 0, orig_width, orig_height)

        # Calculate how much space the rotated rectangle occupies
        transform = QTransform().rotate(self._rotation)
        rotated_rect = transform.mapRect(self.irect)

        # Update bounding rect with padding to include the rotated corners
        padding = 10
        self.brect = rotated_rect.adjusted(-padding, -padding, padding, padding)

        # Center the image rectangle within the new bounding rect
        self.irect.moveCenter(self.brect.center())

        self.scene().setSceneRect(self.brect)
        self.selections.updateSelectionVisibility()

    currentPageIndex = property(getCurrentPageIndex, setCurrentPageIndex)

    def previousPage(self):
        self.currentPageIndex = self.currentPageIndex-1

    def nextPage(self):
        self.currentPageIndex = self.currentPageIndex+1

    def firstPage(self):
        self.currentPageIndex = 0

    def secondPage(self):
        if self.numPages() > 1:
            self.currentPageIndex = 1
        else:
            self.currentPageIndex = 0

    def lastPage(self):
        self.currentPageIndex = self.numPages()-1

    def getImage(self, idx):
        if idx < 0 or idx >= self.numPages():
            return None
        if self._images[idx] is None:
            self._images[idx] = self.cacheImage(idx)
        return self._images[idx]        

    def mousePressEvent(self, event):
        self.selections.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.selections.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.selections.mouseReleaseEvent(event)

    def load(self, filename):
        self.reset()
        self.doLoad(filename)
        self._images = [None for i in range(self.numPages())]
        self.secondPage()

    # To be implemented in deriving classes:

    def doLoad(self, filename):
        pass

    def numPages(self):
        return 0

    def isEmpty(self):
        return self.numPages() <= 0

    def cacheImage(self, idx):        
        return None

    def pageGetRotation(self, idx):        
        return 0

    def cropValues(self, idx):
        def adjustForOrientation(cv):
            if r == 90: # Landscape
                return [ cv[1], cv[2], cv[3], cv[0] ]
            elif r == 180: # UpsideDown
                return [ cv[2], cv[3], cv[0], cv[1] ]
            elif r == 270: # Seascape
                return [ cv[3], cv[0], cv[1], cv[2] ]
            else: # r == 0, Portrait
                return cv
        crop_values = self.selections.cropValues(idx)
        r = self.pageGetRotation(idx)
        return [ adjustForOrientation(cv) for cv in crop_values ]

    def getRotatedCropPoints(self, rect, angle):
        """Example of how to transform crop coordinates by an arbitrary angle."""
        transform = QTransform()
        transform.rotate(angle)
        # Map the crop rect through the same rotation matrix used for display
        return transform.map(rect)

class MuPDFViewerItem(AbstractViewerItem):
    """Viewer implementation which uses PyMuPDF to display PDF documents."""
    def reset(self):
        AbstractViewerItem.reset(self)
        self._pdfdoc = None

    def doLoad(self, filename):
        self._pdfdoc = fitz.open(filename)
        # if self._pdfdoc:
        #     self._pdfdoc.setRenderHint(Poppler.Document.Antialiasing and
        #             Poppler.Document.TextAntialiasing)

    def numPages(self):
        if self._pdfdoc is None:
            return 0
        else:
            return len(self._pdfdoc)

    def cacheImage(self, idx):
        page = self._pdfdoc[idx]
        image_list = page.get_images(full=True)

        if not image_list:
            # Fallback: if no image found, render the empty page
            pix = page.get_pixmap(dpi=150)
        else:
            # Get the first image on the page
            # image_list[0] = (xref, smask, width, height, bpc, colorspace, ...)
            xref = image_list[0][0]
            base_image = self._pdfdoc.extract_image(xref)
            image_bytes = base_image["image"]

            # Load the raw bytes into QImage
            return QImage.fromData(image_bytes)

        return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)

    def pageGetRotation(self, idx):
        page = self._pdfdoc[idx]
        return page.rotation

class PopplerViewerItem(AbstractViewerItem):
    """Viewer implementation which uses Poppler to display PDF documents."""
    def reset(self):
        AbstractViewerItem.reset(self)
        self._pdfdoc = None

    def doLoad(self, filename):
        self._pdfdoc = Poppler.Document.load(filename)
        if self._pdfdoc:
            self._pdfdoc.setRenderHint(Poppler.Document.Antialiasing and
                    Poppler.Document.TextAntialiasing)

    def numPages(self):
        if self._pdfdoc is None:    
            return 0
        else:
            return self._pdfdoc.numPages()

    def cacheImage(self, idx):        
        page = self._pdfdoc.page(idx)
        return page.renderToImage(96.0, 96.0) # dpi = 96
        # return page.renderToImage() # default dpi = 72

    def pageGetRotation(self, idx):        
        page = self._pdfdoc.page(idx)
        o = page.orientation()
        if o == page.Landscape:
            return 90
        elif o == page.UpsideDown:
            return 180
        elif o == page.Seascape:
            return 270
        else: # o == page.Portrait
            return 0


# determine whether to use PopplerQt or PyMuPDF for rendering
POPPLERQT = 1
PYMUPDF = 2
lib_render = 0

from krop.config import PYQT6

# for PyQt6 use PyMuPDF
if PYQT6:
    try:
        import fitz
        lib_render = PYMUPDF
    except ImportError:
        _msg = "Please install PyMuPDF first (PyQt6 is being used)."\
            "\n\tOn recent versions of Ubuntu, the following should do the trick:"\
            "\n\tsudo apt-get install python3-pymupdf"
        raise RuntimeError(_msg)
else:
    # PyQt5 was requested
    if not '--use-poppler' in sys.argv:
        try:
            import fitz
            lib_render = PYMUPDF
        except ImportError:
            pass
    if not lib_render:
        try:
            from popplerqt5 import Poppler
            lib_render = POPPLERQT
        except ImportError:
            pass
    # complain if no version is available
    if not lib_render:
        _msg = "Please install PyMuPDF or Poppler Qt first (PyQt5 is being used)."\
            "\n\tOn versions of Ubuntu such as 22.04, one of the following should do the trick:"\
            "\n\tsudo apt install python3-fitz"\
            "\n\tsudo apt install python3-poppler-qt5"
        raise RuntimeError(_msg)

if lib_render == PYMUPDF:
    ViewerItem = MuPDFViewerItem
    print("Using PyMuPDF for rendering.", file=sys.stderr)
else:
    ViewerItem = PopplerViewerItem
    print("Using PopplerQt for rendering.", file=sys.stderr)
