import os
import rasterio
import numpy as np
from rasterio.transform import xy
import laspy
from scipy.spatial import cKDTree
from pyproj import Transformer

from qgis.PyQt import uic, QtWidgets, QtGui, QtCore
from qgis.gui import QgsFileWidget

# Load the UI file
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'demo_dialog_base.ui'))

# Custom QGraphicsView for zooming using mouse wheel
class ZoomableGraphicsView(QtWidgets.QGraphicsView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._zoom_factor = 1.0
        self._zoom_step = 1.15
        self._min_zoom = 0.05
        self._max_zoom = 10

    def wheelEvent(self, event):
        old_pos = self.mapToScene(event.pos())
        if event.angleDelta().y() > 0:
            zoom = self._zoom_step
        else:
            zoom = 1 / self._zoom_step

        new_zoom = self._zoom_factor * zoom
        if self._min_zoom <= new_zoom <= self._max_zoom:
            self._zoom_factor = new_zoom
            self.scale(zoom, zoom)

            new_pos = self.mapToScene(event.pos())
            delta = new_pos - old_pos
            self.translate(delta.x(), delta.y())

        event.accept()


class DemoDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(DemoDialog, self).__init__(parent)
        self.setupUi(self)

        # Connect signals to slots
        self.LidarFile_2.fileChanged.connect(self.on_lidar_file_selected)
        self.MXfile.fileChanged.connect(self.on_mx_file_selected)
        self.pushButton.clicked.connect(self.load_mx_image)
        self.maxbutton.clicked.connect(self.zoom_in)
        self.minbutton.clicked.connect(self.zoom_out)

        # Replace graphicsView with our custom ZoomableGraphicsView
        original_view = self.graphicsView
        self.scene = QtWidgets.QGraphicsScene()
        self.graphicsView = ZoomableGraphicsView(self)
        self.graphicsView.setObjectName("graphicsView")
        self.graphicsView.setScene(self.scene)
        self.graphicsView.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.graphicsView.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.graphicsView.setAlignment(QtCore.Qt.AlignCenter)
        self.graphicsView.setMouseTracking(True)
        self.graphicsView.viewport().installEventFilter(self)

        # Replace the widget in the layout
        layout = original_view.parent().layout()
        if layout:
            layout.replaceWidget(original_view, self.graphicsView)
            original_view.deleteLater()

        self.pixmap_item = None
        self.zoom_factor = 1.0
        self.geo_transform = None

        # LiDAR-related
        self.lidar_points = None
        self.kd_tree = None

    def on_lidar_file_selected(self, file_path):
        """Triggered when a Lidar file is selected."""
        print(f"Selected Lidar File: {file_path}")
        try:
            las = laspy.read(file_path)
            x, y, z = las.x, las.y, las.z
            self.lidar_points = np.vstack((x, y, z)).T
            self.kd_tree = cKDTree(self.lidar_points[:, :2])
            print(f"Loaded {len(self.lidar_points)} LiDAR points.")
        except Exception as e:
            print(f"Error loading LiDAR file: {e}")

    def on_mx_file_selected(self, file_path):
        """Triggered when an MX file is selected."""
        print(f"Selected MX File: {file_path}")
        self.mx_file_path = file_path

    def normalize_band(self, band):
        """Normalize band values to 8-bit range (0–255)."""
        return ((band - band.min()) / (band.max() - band.min()) * 255).astype(np.uint8)

    def load_mx_image(self):
        """Load the MX GeoTIFF image and display it."""
        if hasattr(self, 'mx_file_path') and os.path.exists(self.mx_file_path):
            try:
                with rasterio.open(self.mx_file_path) as dataset:
                    print(f"GeoTransform: {dataset.transform}")
                    print(f"CRS: {dataset.crs}")
                    print(f"Bands: {dataset.count}")

                    if dataset.count >= 3:
                        image_array = np.dstack([
                            self.normalize_band(dataset.read(1)),
                            self.normalize_band(dataset.read(2)),
                            self.normalize_band(dataset.read(3))
                        ])
                        q_format = QtGui.QImage.Format_RGB888
                        height, width, _ = image_array.shape
                        qimage = QtGui.QImage(image_array.data, width, height, 3 * width, q_format)
                    else:
                        image_array = self.normalize_band(dataset.read(1))
                        height, width = image_array.shape
                        qimage = QtGui.QImage(image_array.data, width, height, width, QtGui.QImage.Format_Grayscale8)

                    pixmap = QtGui.QPixmap.fromImage(qimage)
                    self.geo_transform = dataset.transform

                    if not pixmap.isNull():
                        self.scene.clear()
                        self.pixmap_item = self.scene.addPixmap(pixmap)
                        self.zoom_factor = 1.0
                        self.graphicsView.setScene(self.scene)
                        self.fit_image_to_view()
                    else:
                        print("Error: Unable to load image.")
            except Exception as e:
                print(f"Error loading image: {e}")
        else:
            print("No valid MX file selected.")

    def fit_image_to_view(self):
        """Ensure the image fits within the QGraphicsView."""
        if self.pixmap_item:
            view_rect = self.graphicsView.viewport().rect()
            scene_rect = self.pixmap_item.pixmap().rect()
            scale = min(view_rect.width() / scene_rect.width(), view_rect.height() / scene_rect.height())
            self.pixmap_item.setScale(scale)
            self.graphicsView.setSceneRect(self.pixmap_item.sceneBoundingRect())

    def zoom_in(self):
        """Zoom in the image."""
        if self.pixmap_item:
            self.graphicsView.scale(1.2, 1.2)

    def zoom_out(self):
        """Zoom out the image."""
        if self.pixmap_item:
            self.graphicsView.scale(1 / 1.2, 1 / 1.2)

    def pixel_to_geo(self, x, y):
        if self.geo_transform:
            proj_x, proj_y = xy(self.geo_transform, y, x)
            if not hasattr(self, 'transformer'):
                with rasterio.open(self.mx_file_path) as dataset:
                    crs_src = dataset.crs
                self.transformer = Transformer.from_crs(crs_src, "EPSG:4326", always_xy=True)
            lon, lat = self.transformer.transform(proj_x, proj_y)
            return lon, lat
        return None, None

    def eventFilter(self, source, event):
        """Track mouse movement and update labels."""
        if source == self.graphicsView.viewport() and event.type() == QtCore.QEvent.MouseMove:
            if self.pixmap_item:
                scene_pos = self.graphicsView.mapToScene(event.pos())
                image_pos = self.pixmap_item.mapFromScene(scene_pos)
                x, y = int(image_pos.x()), int(image_pos.y())

                if 0 <= x < self.pixmap_item.pixmap().width() and 0 <= y < self.pixmap_item.pixmap().height():
                    lon, lat = self.pixel_to_geo(x, y)
                    if lon is not None and lat is not None:
                        self.Xlabel.setText(f"Lon: {lon:.6f}")
                        self.Ylabel.setText(f"Lat: {lat:.6f}")

                        z_text = "N/A"
                        if self.kd_tree is not None:
                            dist, idx = self.kd_tree.query([lon, lat], k=1)
                            if dist < 1.0:  # threshold in degrees
                                z = self.lidar_points[idx, 2]
                                z_text = f"{z:.2f}"
                        self.Zlabel.setText(f"Z: {z_text}")
        return super().eventFilter(source, event)
