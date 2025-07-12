import os
from PyQt5.QtWidgets import QDialog
from PyQt5 import uic
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from osgeo import gdal, osr

class LidarConversionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Load the .ui file dynamically
        uic.loadUi('lidar_conversion_dialog_base.ui', self)

        # Connect button
        self.pushButton.clicked.connect(self.convert_to_geotiff)

    def get_decimal_from_dms(self, dms, ref):
        degrees, minutes, seconds = dms
        dec = degrees[0]/degrees[1] + minutes[0]/(minutes[1]*60) + seconds[0]/(seconds[1]*3600)
        return -dec if ref in ['S', 'W'] else dec

    def extract_gps(self, image_path):
        img = Image.open(image_path)
        exif = img._getexif()
        gps = {}
        if exif:
            for tag, val in exif.items():
                if TAGS.get(tag) == "GPSInfo":
                    for t in val:
                        gps[GPSTAGS.get(t, t)] = val[t]
        if "GPSLatitude" in gps and "GPSLongitude" in gps:
            lat = self.get_decimal_from_dms(gps["GPSLatitude"], gps["GPSLatitudeRef"])
            lon = self.get_decimal_from_dms(gps["GPSLongitude"], gps["GPSLongitudeRef"])
            return lat, lon
        return None, None

    def convert_to_geotiff(self):
        input_path = self.mQgsFileWidget.filePath()
        output_path = self.mQgsFileWidget_2.filePath()

        if not os.path.exists(input_path):
            self.label_3.setText("Input image not found.")
            return

        lat, lon = self.extract_gps(input_path)
        if lat is None or lon is None:
            self.label_3.setText("No GPS metadata found in image.")
            return

        # Open image with PIL
        img = Image.open(input_path)
        img = img.convert('RGB')
        width, height = img.size
        data = img.tobytes()

        # Set pixel resolution (example: ~1m per pixel, can be adjusted)
        pixel_size = 0.00001  # ~1.11 meters at equator

        driver = gdal.GetDriverByName('GTiff')
        dataset = driver.Create(output_path, width, height, 3, gdal.GDT_Byte)

        # Origin is upper-left corner of the image
        geotransform = [
            lon - (width // 2) * pixel_size,
            pixel_size,
            0,
            lat + (height // 2) * pixel_size,
            0,
            -pixel_size
        ]
        dataset.SetGeoTransform(geotransform)

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)  # WGS 84
        dataset.SetProjection(srs.ExportToWkt())

        r, g, b = img.split()
        dataset.GetRasterBand(1).WriteArray(gdalnumeric.numpy.array(r))
        dataset.GetRasterBand(2).WriteArray(gdalnumeric.numpy.array(g))
        dataset.GetRasterBand(3).WriteArray(gdalnumeric.numpy.array(b))
        dataset.FlushCache()
        dataset = None

        self.label_3.setText("GeoTIFF created successfully.")
