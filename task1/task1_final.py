from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFileDestination,
                       QgsRasterLayer)
import processing

class AccessibilityIsochronesZ(QgsProcessingAlgorithm):
    INPUT_ROADS = 'INPUT_ROADS'
    MANUAL_H_FIELD = 'MANUAL_H_FIELD'
    INPUT_CONTOURS = 'INPUT_CONTOURS'
    STOPS_A = 'STOPS_A'
    STOPS_B = 'STOPS_B'
    TRAVEL_COST = 'TRAVEL_COST'
    OUTPUT_A = 'OUTPUT_A'
    OUTPUT_B = 'OUTPUT_B'
    OUTPUT_INTERSECTION = 'OUTPUT_INTERSECTION'

    def createInstance(self):
        return AccessibilityIsochronesZ()

    def name(self):
        return 'task1_final'

    def displayName(self):
        return 'задача 1 финал'

    def group(self):
        return 'хакатон'

    def groupId(self):
        return 'hackathon'
    
    #объявление переменных (поля в UI)
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ROADS, 
            'Слой УДС', 
            types=[QgsProcessing.TypeVectorLine])
        )
        
        self.addParameter(QgsProcessingParameterField(
            self.MANUAL_H_FIELD, 
            'Поле с ручной высотой', 
            parentLayerParameterName=self.INPUT_ROADS, 
            type=QgsProcessingParameterField.Numeric, 
            optional=True)
        )
        
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_CONTOURS, 
            'Слой Изолиний (3D)', 
            types=[QgsProcessing.TypeVectorLine])
        )
        
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.STOPS_A, 
            'Остановки А', 
            types=[QgsProcessing.TypeVectorPoint])
        )
        
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.STOPS_B, 
            'Остановки Б', 
            types=[QgsProcessing.TypeVectorPoint])
        )
        
        self.addParameter(QgsProcessingParameterNumber(
            self.TRAVEL_COST, 
            'Лимит (Cost)', 
            type=QgsProcessingParameterNumber.Double, 
            defaultValue=500)
        )
        
        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT_A, 'Полигон А', fileFilter='GeoPackage (*.gpkg)'))
        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT_B, 'Полигон Б', fileFilter='GeoPackage (*.gpkg)'))
        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT_INTERSECTION, 'Пересечение', fileFilter='GeoPackage (*.gpkg)'))

    def processAlgorithm(self, parameters, context, feedback):
        source_roads = self.parameterAsVectorLayer(parameters, self.INPUT_ROADS, context)
        source_contours = self.parameterAsVectorLayer(parameters, self.INPUT_CONTOURS, context)
        limit_val = self.parameterAsDouble(parameters, self.TRAVEL_COST, context)
        manual_h_field = self.parameterAsString(parameters, self.MANUAL_H_FIELD, context)
        
        path_a = self.parameterAsFileOutput(parameters, self.OUTPUT_A, context)
        path_b = self.parameterAsFileOutput(parameters, self.OUTPUT_B, context)
        path_inter = self.parameterAsFileOutput(parameters, self.OUTPUT_INTERSECTION, context)

        # шаг 0. строим tin
        feedback.pushInfo('шаг 0: строим tin из геометрии...')

        tin_data = f"{source_contours.source()}::~::0::~::2::~::1"
        
        ext_str = f'{source_contours.extent().xMinimum()},{source_contours.extent().xMaximum()},{source_contours.extent().yMinimum()},{source_contours.extent().yMaximum()} [{source_contours.crs().authid()}]'
        
        tin_result = processing.run("qgis:tininterpolation", {
            'INTERPOLATION_DATA': tin_data,
            'METHOD': 0,
            'EXTENT': ext_str,
            'PIXEL_SIZE': 5.0,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }, context=context, feedback=feedback)
        
        tin_path = tin_result['OUTPUT']

        # прогрев растра
        temp_raster = QgsRasterLayer(tin_path, "temp_check", "gdal")
        if temp_raster.isValid():
            temp_raster.dataProvider().bandStatistics(1)
        else:
            feedback.reportError('ошибка: tin не создан!')
            return {}

        # шаг 1. натягиваем высоту
        feedback.pushInfo('шаг 1: натягиваем высоту...')
        draped = processing.run("native:setzfromraster", {
            'INPUT': source_roads, 
            'RASTER': tin_path, 
            'BAND': 1, 
            'NODATA': 0, 
            'SCALE': 1, 
            'OUTPUT': 'memory:draped'
        }, context=context, feedback=feedback)['OUTPUT']

        # шаг 2. считаем вес
        feedback.pushInfo('шаг 2: считаем вес...')
        base_calc = 'abs(z(start_point($geometry)) - z(end_point($geometry)))'
        
        #учитвыем ручное поле если оно есть
        if manual_h_field and manual_h_field != 'NULL' and manual_h_field != '':
            part_h = f'CASE WHEN "{manual_h_field}" IS NOT NULL AND "{manual_h_field}" > 0 THEN "{manual_h_field}" ELSE {base_calc} END'
        else:
            part_h = base_calc

        cost_expr = f'length($geometry) + (5 * coalesce({part_h}, 0))'
        
        #расчет скорости для использования service area: fastest
        speed_expr = f'3.6 * length($geometry) / ( ({cost_expr}) + 0.001 )'

        weighted = processing.run("native:fieldcalculator", {
            'INPUT': draped, 
            'FIELD_NAME': 'fake_speed', 
            'FIELD_TYPE': 0, 
            'FIELD_LENGTH': 10, 
            'FIELD_PRECISION': 5, 
            'FORMULA': speed_expr, 
            'OUTPUT': 'memory:weighted'
        }, context=context, feedback=feedback)['OUTPUT']

        # шаг 3. полигон А
        feedback.pushInfo('шаг 3: полигон А...')
        lines_a = processing.run("qgis:serviceareafromlayer", {
            'INPUT': weighted, 
            'STRATEGY': 1, 
            'SPEED_FIELD': 'fake_speed', 
            'TRAVEL_COST': limit_val, 
            'START_POINTS': self.parameterAsVectorLayer(parameters, self.STOPS_A, context), 
            'OUTPUT_LINES': 'memory:lines_a'
        }, context=context, feedback=feedback)['OUTPUT_LINES']
        
        #buffer и лечение геометрии
        poly_a_raw = processing.run("native:buffer", {
            'INPUT': lines_a, 
            'DISTANCE': 35, 
            'DISSOLVE': True, 
            'OUTPUT': 'memory:poly_a_raw'
        }, context=context, feedback=feedback)['OUTPUT']
        
        processing.run("native:fixgeometries", {'INPUT': poly_a_raw, 'OUTPUT': path_a}, context=context, feedback=feedback)

        # шаг 4. полигон Б
        feedback.pushInfo('шаг 4: полигон Б...')
        lines_b = processing.run("qgis:serviceareafromlayer", {
            'INPUT': weighted, 
            'STRATEGY': 1, 
            'SPEED_FIELD': 'fake_speed', 
            'TRAVEL_COST': limit_val, 
            'START_POINTS': self.parameterAsVectorLayer(parameters, self.STOPS_B, context), 
            'OUTPUT_LINES': 'memory:lines_b'
        }, context=context, feedback=feedback)['OUTPUT_LINES']
        
        #buffer и лечение геометрии
        poly_b_raw = processing.run("native:buffer", {
            'INPUT': lines_b, 
            'DISTANCE': 35, 
            'DISSOLVE': True, 
            'OUTPUT': 'memory:poly_b_raw'
        }, context=context, feedback=feedback)['OUTPUT']
        
        processing.run("native:fixgeometries", {'INPUT': poly_b_raw, 'OUTPUT': path_b}, context=context, feedback=feedback)

        # шаг 5. пересечение
        feedback.pushInfo('шаг 5: пересечение...')
        processing.run("native:intersection", {'INPUT': path_a, 'OVERLAY': path_b, 'OUTPUT': path_inter}, context=context, feedback=feedback)

        return {self.OUTPUT_A: path_a, self.OUTPUT_B: path_b, self.OUTPUT_INTERSECTION: path_inter}