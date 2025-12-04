from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterPoint,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingException,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsWkbTypes,
    QgsFeatureSink,
    QgsGeometry
)
import processing


class IsochronesFromNetworkV6(QgsProcessingAlgorithm):

    INPUT_NETWORK = 'INPUT_NETWORK'
    MODE = 'MODE'
    INTERVALS = 'INTERVALS'
    START_POINT = 'START_POINT'
    WALK_SPEED_FIELD = 'WALK_SPEED_FIELD'
    BIKE_SPEED_FIELD = 'BIKE_SPEED_FIELD'
    CAR_SPEED_FIELD = 'CAR_SPEED_FIELD'
    POP_LAYER = 'POP_LAYER'
    POP_FIELD = 'POP_FIELD'
    CONTOURS = 'CONTOURS'
    CONTOURS_Z = 'CONTOURS_Z'
    BUFFER_DIST = 'BUFFER_DIST'
    OUTPUT = 'OUTPUT'
    OUTPUT_START = 'OUTPUT_START'
    OUTPUT_WALKNET = 'OUTPUT_WALKNET'


    def tr(self, string):
        return QCoreApplication.translate('IsochronesFromNetworkV6', string)

    def createInstance(self):
        return IsochronesFromNetworkV6()

    def name(self):
        return 'isochrones_from_network_v6'

    def displayName(self):
        return self.tr('Изохроны по сети УДС')

    def group(self):
        return self.tr('Пользовательские скрипты')

    def groupId(self):
        return 'user_scripts'

    def shortHelpString(self):
        return self.tr(
            'Строит изохроны от точки по графу УДС для пеших, велосипедов и личного авто.\n'
            'Для пешего режима при наличии слоя изолиний учитывается перепад высоты по\n'
            'формуле cost = длина + 5 * |Δh|, скорость на ребре снижается по уклону.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_NETWORK,
                self.tr('Граф улично-дорожной сети (УДС)'),
                [QgsProcessing.TypeVectorLine]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterEnum(
                self.MODE,
                self.tr('Способ передвижения'),
                options=[
                    self.tr('Пешком'),
                    self.tr('Велосипед'),
                    self.tr('Личный автомобиль'),
                ],
                defaultValue=0
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.WALK_SPEED_FIELD,
                self.tr('Поле скорости ПЕШКОМ (км/ч)'),
                parentLayerParameterName=self.INPUT_NETWORK,
                type=QgsProcessingParameterField.Any,
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.BIKE_SPEED_FIELD,
                self.tr('Поле скорости ВЕЛО (км/ч)'),
                parentLayerParameterName=self.INPUT_NETWORK,
                type=QgsProcessingParameterField.Any,
                optional=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.CAR_SPEED_FIELD,
                self.tr('Поле скорости АВТО (км/ч)'),
                parentLayerParameterName=self.INPUT_NETWORK,
                type=QgsProcessingParameterField.Any,
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.INTERVALS,
                self.tr('Интервалы времени, мин (через запятую, напр. 10,20,30)'),
                defaultValue='10,20,30'
            )
        )

        self.addParameter(
            QgsProcessingParameterPoint(
                self.START_POINT,
                self.tr('Точка старта (клик по карте)'),
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.POP_LAYER,
                self.tr('Слой населения (здания/точки)'),
                [QgsProcessing.TypeVectorAnyGeometry],
                optional=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.POP_FIELD,
                self.tr('Поле с численностью населения'),
                parentLayerParameterName=self.POP_LAYER,
                type=QgsProcessingParameterField.Numeric,
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.CONTOURS,
                self.tr('Изолинии рельефа'),
                [QgsProcessing.TypeVectorLine],
                optional=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.CONTOURS_Z,
                self.tr('Поле высоты изолиний'),
                parentLayerParameterName=self.CONTOURS,
                type=QgsProcessingParameterField.Numeric,
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.BUFFER_DIST,
                self.tr('Ширина буфера вокруг линий, м'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=50.0,
                minValue=0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Изохроны'),
                QgsProcessing.TypeVectorPolygon
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_START,
                self.tr('Точка старта'),
                QgsProcessing.TypeVectorPoint
            )
        )
        
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_WALKNET,
                self.tr('Пешеходная сеть'),
                QgsProcessing.TypeVectorLine
            )
        )


    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsVectorLayer(parameters, self.INPUT_NETWORK, context)
        if network is None:
            raise QgsProcessingException(self.tr('Не удалось получить слой сети.'))
        if network.crs().isGeographic():
            feedback.pushWarning(
                self.tr('...')
            )
        feedback.pushInfo(self.tr('Исправление геометрии сети (Fix geometries)...'))
        fix_res = processing.run(
            'native:fixgeometries',
            {'INPUT': network, 'OUTPUT': 'TEMPORARY_OUTPUT'},
            context=context,
            feedback=feedback
        )
        net_fixed = fix_res['OUTPUT']
        crs_authid = net_fixed.crs().authid()
        intervals_str = self.parameterAsString(parameters, self.INTERVALS, context)
        try:
            intervals = [
                float(v.strip().replace(',', '.'))
                for v in intervals_str.replace(';', ',').split(',')
                if v.strip() != ''
            ]
        except Exception:
            raise QgsProcessingException(
                self.tr('Не удалось разобрать список интервалов. Пример: 5,10,15')
            )
        if not intervals:
            raise QgsProcessingException(self.tr('Нужно задать хотя бы один интервал.'))
        intervals = sorted(intervals)
        mode_index = self.parameterAsEnum(parameters, self.MODE, context)
        mode_labels = ['Пешком', 'Велосипед', 'Авто']
        walk_field = self.parameterAsString(parameters, self.WALK_SPEED_FIELD, context)
        bike_field = self.parameterAsString(parameters, self.BIKE_SPEED_FIELD, context)
        car_field  = self.parameterAsString(parameters, self.CAR_SPEED_FIELD,  context)
        if mode_index == 0:
            speed_field = walk_field or ''
            default_speed = 4.0
        elif mode_index == 1:
            speed_field = bike_field or ''
            default_speed = 15.0
        else:
            speed_field = car_field or ''
            default_speed = 20.0
        if not speed_field:
            feedback.pushInfo(
                self.tr('Поле скорости не указано. '
                        'Используем постоянную скорость {0} км/ч по всей сети.')
                .format(default_speed)
            )
        start_point = self.parameterAsPoint(parameters, self.START_POINT, context)
        start_point_str = f'{start_point.x()},{start_point.y()} [{crs_authid}]'
        pop_layer = self.parameterAsVectorLayer(parameters, self.POP_LAYER, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        pop_data = []
        if pop_layer is not None and pop_field:
            if pop_layer.crs() != net_fixed.crs():
                feedback.pushWarning(
                    self.tr('CRS слоя населения отличается от CRS сети. '
                            'Лучше перепроецировать слой населения в тот же CRS.')
                )
            for f in pop_layer.getFeatures():
                try:
                    val = float(f[pop_field])
                except Exception:
                    continue
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                pop_data.append((g, val))
            feedback.pushInfo(
                self.tr('Загружено {0} объектов населения.').format(len(pop_data))
            )
        else:
            feedback.pushInfo(
                self.tr('Слой населения не задан — считаем только площадь.')
            )
        buffer_dist = self.parameterAsDouble(parameters, self.BUFFER_DIST, context)
        contours = self.parameterAsVectorLayer(parameters, self.CONTOURS, context)
        contours_z = self.parameterAsString(parameters, self.CONTOURS_Z, context)
        walk_network = net_fixed
        walk_speed_field_name = ''
        if mode_index == 0 and contours is not None and contours_z:
            if contours.crs() != net_fixed.crs():
                feedback.pushWarning(
                    self.tr('CRS изолиний отличается от CRS сети. '
                            'Лучше перепроецировать изолинии в CRS сети.')
                )
            feedback.pushInfo(self.tr('Шаг 1: интерполяция DEM по изолиниям...'))
            extent = net_fixed.extent()
            extent_str = (
                f'{extent.xMinimum()},{extent.xMaximum()},'
                f'{extent.yMinimum()},{extent.yMaximum()} [{crs_authid}]'
            )
            z_field_index = contours.fields().lookupField(contours_z)
            if z_field_index < 0:
                raise QgsProcessingException(
                    self.tr(f'Поле высоты "{contours_z}" не найдено в слое изолиний.')
                )
            contours_src = parameters[self.CONTOURS]
            interp_str = f'{contours_src}::~::0::~::{z_field_index}::~::1'
            tin_res = processing.run(
                'qgis:tininterpolation',
                {
                    'INTERPOLATION_DATA': interp_str,
                    'METHOD': 0,
                    'EXTENT': extent_str,
                    'PIXEL_SIZE': 30,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context,
                feedback=feedback
            )
            dem = tin_res['OUTPUT']
            feedback.pushInfo(self.tr('Шаг 2: привязка высоты к ребрам УДС...'))
            setz_res = processing.run(
                'native:setzfromraster',
                {
                    'INPUT': net_fixed,
                    'RASTER': dem,
                    'BAND': 1,
                    'NODATA': -9999,
                    'SCALE': 1,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context,
                feedback=feedback
            )
            net_z = setz_res['OUTPUT']
            feedback.pushInfo(self.tr('Шаг 3: расчёт скорости пешехода с учётом уклона...'))
            cost_expr = (
                'length($geometry) + (5 * coalesce('
                'abs(z(start_point($geometry)) - z(end_point($geometry))), 0))'
            )
            speed_expr = (
                f'CASE WHEN length($geometry) = 0 THEN {default_speed} '
                f'ELSE ({default_speed} * length($geometry)) / ({cost_expr}) END'
            )
            fc_res = processing.run(
                'native:fieldcalculator',
                {
                    'INPUT': net_z,
                    'FIELD_NAME': 'walk_spd',
                    'FIELD_TYPE': 1,  # float
                    'FIELD_LENGTH': 10,
                    'FIELD_PRECISION': 3,
                    'NEW_FIELD': True,
                    'FORMULA': speed_expr,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context,
                feedback=feedback
            )
            walk_network = fc_res['OUTPUT']
            walk_speed_field_name = 'walk_spd'
        (walk_sink, walk_dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_WALKNET,
            context,
            walk_network.fields(),
            walk_network.wkbType(),
            walk_network.crs()
        )
        for f in walk_network.getFeatures():
            walk_sink.addFeature(f, QgsFeatureSink.FastInsert)
        fields = QgsFields()
        fields.append(QgsField('id', QVariant.Int))
        fields.append(QgsField('t_min', QVariant.Double, 'double', 10, 2))
        fields.append(QgsField('mode', QVariant.String, 'string', 32))
        fields.append(QgsField('area_km2', QVariant.Double, 'double', 20, 3))
        if pop_data:
            fields.append(QgsField('pop_sum', QVariant.Double, 'double', 20, 2))
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.MultiPolygon,
            net_fixed.crs()
        )
        pt_fields = QgsFields()
        pt_fields.append(QgsField('id', QVariant.Int))
        pt_fields.append(QgsField('mode', QVariant.String, 'string', 32))
        (sink_pt, dest_pt_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_START,
            context,
            pt_fields,
            QgsWkbTypes.Point,
            net_fixed.crs()
        )
        pt_feat = QgsFeature(pt_fields)
        pt_feat.setGeometry(QgsGeometry.fromPointXY(start_point))
        pt_feat['id'] = 1
        pt_feat['mode'] = mode_labels[mode_index]
        sink_pt.addFeature(pt_feat, QgsFeatureSink.FastInsert)
        total_steps = max(1, len(intervals) * 3)
        step = 0
        feedback.pushInfo(self.tr('Поиск расстояния до ближайшей линии сети...'))
        pt_geom = QgsGeometry.fromPointXY(start_point)
        min_dist = None
        for feat in net_fixed.getFeatures():
            g = feat.geometry()
            if g is None or g.isEmpty():
                continue
            d = g.distance(pt_geom)
            if min_dist is None or d < min_dist:
                min_dist = d
        if min_dist is None:
            min_dist = 0.0
        access_walk_speed = 4.0
        access_time_min = (min_dist / 1000.0) / access_walk_speed * 60.0
        feedback.pushInfo(
            self.tr('Расстояние до ближайшей линии сети: {0:.1f} м '
                    '(~{1:.1f} мин пешком)').format(min_dist, access_time_min)
        )
        for idx, minutes in enumerate(intervals, start=1):
            if feedback.isCanceled():
                break
            feedback.pushInfo(self.tr(f'Интервал {minutes} мин'))
            net_minutes = minutes - access_time_min
            if net_minutes <= 0:
                feedback.pushWarning(
                    self.tr('Интервал {0} мин меньше времени подхода к сети '
                            '({1:.1f} мин). Изохрона не строится.')
                    .format(minutes, access_time_min)
                )
                continue
            travel_time_hours = net_minutes / 60.0
            max_distance_m = default_speed * travel_time_hours * 1000.0
            if mode_index == 0 and walk_speed_field_name:
                feedback.pushInfo(
                    self.tr('Пешком: учитываем подход к сети ({0:.1f} мин), '
                            'по сети остаётся {1:.1f} мин')
                    .format(access_time_min, net_minutes)
                )
                sa_input_layer = walk_network
                strategy = 1
                travel_cost = net_minutes * 60.0
                sa_speed_field = walk_speed_field_name
                sa_default_speed = default_speed
            else:
                feedback.pushInfo(
                    self.tr('Режим {0}: учитываем подход к сети ({1:.1f} мин), '
                            'по сети остаётся {2:.1f} мин')
                    .format(mode_labels[mode_index], access_time_min, net_minutes)
                )
                sa_input_layer = net_fixed
                strategy = 0
                travel_cost = max_distance_m
                sa_speed_field = ''
                sa_default_speed = 0
            sa_params = {
                'INPUT': sa_input_layer,
                'START_POINT': start_point_str,
                'STRATEGY': strategy,
                'TRAVEL_COST': travel_cost,
                'DIRECTION_FIELD': '',
                'VALUE_FORWARD': '',
                'VALUE_BACKWARD': '',
                'VALUE_BOTH': '',
                'DEFAULT_DIRECTION': 2,
                'SPEED_FIELD': sa_speed_field,
                'DEFAULT_SPEED': sa_default_speed,
                'TOLERANCE': 0.0,
                'OUTPUT_LINES': 'TEMPORARY_OUTPUT',
                'OUTPUT': 'TEMPORARY_OUTPUT',
                'INCLUDE_BOUNDS': False
            }
            sa_result = processing.run(
                'qgis:serviceareafrompoint',
                sa_params,
                context=context,
                feedback=feedback
            )
            lines_layer = sa_result['OUTPUT_LINES']
            if lines_layer is None or lines_layer.featureCount() == 0:
                feedback.pushWarning(
                    self.tr('Для интервала {0} мин не найдено достижимых ребер. '
                            'Возможно, точка далека от сети или время слишком мало.')
                    .format(minutes)
                )
                continue
            step += 1
            feedback.setProgress(int(100.0 * step / total_steps))
            buffer_res = processing.run(
                'native:buffer',
                {
                    'INPUT': lines_layer,
                    'DISTANCE': buffer_dist,
                    'SEGMENTS': 8,
                    'END_CAP_STYLE': 0,
                    'JOIN_STYLE': 0,
                    'MITER_LIMIT': 2,
                    'DISSOLVE': True,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context,
                feedback=feedback
            )
            poly_layer = buffer_res['OUTPUT']
            step += 2
            feedback.setProgress(int(100.0 * step / total_steps))
            if poly_layer is None or poly_layer.featureCount() == 0:
                feedback.pushWarning(
                    self.tr('Не удалось построить полигон изохроны для {0} мин.')
                    .format(minutes)
                )
                continue
            for poly_feat in poly_layer.getFeatures():
                geom = poly_feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                if QgsWkbTypes.isSingleType(geom.wkbType()):
                    geom.convertToMultiType()
                area_km2 = geom.area() / 1_000_000.0
                pop_sum_val = None
                if pop_data:
                    s = 0.0
                    for g, val in pop_data:
                        if g.intersects(geom):
                            s += val
                    pop_sum_val = s
                out_feat = QgsFeature(fields)
                out_feat.setGeometry(geom)
                out_feat['id'] = idx
                out_feat['t_min'] = float(minutes)
                out_feat['mode'] = mode_labels[mode_index]
                out_feat['area_km2'] = area_km2
                if pop_data:
                    out_feat['pop_sum'] = pop_sum_val
                sink.addFeature(out_feat, QgsFeatureSink.FastInsert)
        return {
            self.OUTPUT: dest_id,
            self.OUTPUT_START: dest_pt_id,
            self.OUTPUT_WALKNET: walk_dest_id
        }
