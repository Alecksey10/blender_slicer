# 2. Контракт данных

Контракт — это пакет `slicer_protocol`. Он не содержит алгоритмов и не зависит
от хоста. Все сущности сериализуются в JSON без внешних библиотек.

## 2.1. Единицы и соглашения

| Величина | Единица | Где задаётся |
| --- | --- | --- |
| координаты, длины, радиусы, зазоры | **мм** | контракт |
| углы | **градусы** на границе, радианы внутри | контракт / реализация |
| плотность точек | точек на мм или максимальный шаг в мм | параметры операции |
| кривизна | `1/мм` | материал |
| время | мс | только метрики |

Правила:

* В JSON допускаются только конечные числа. `NaN`, `Infinity`, `-Infinity`
  запрещены и дают `E_NON_FINITE`.
* Хост может работать в метрах (Blender) или сантиметрах (Unreal). Перевод в мм
  делает **адаптер** на границе; движок единицы не конвертирует.
* Плоскость среза: `x` вправо, `y` вверх, правая тройка `(u, v, n)`.
  При рендере в SVG ось `y` переворачивается (экранная система), это
  ответственность рендера, а не контракта.
* Точка — кортеж `(x, y)` (в Python — `tuple[float, float]`, не объект).
  Это компактнее и быстрее для больших массивов. В JSON — `[x, y]`.

## 2.2. Базовые типы

```python
Point2 = tuple[float, float]
Points = tuple[Point2, ...]          # в контракте — неизменяемо
Vec3 = tuple[float, float, float]    # только для адаптера, не для движка

class ContourRole(str, Enum):
    CUT = "cut"        # замкнутый контур реза
    SCORE = "score"    # линия сгиба / надреза
    GUIDE = "guide"    # вспомогательная геометрия, не режется

@dataclass(frozen=True, slots=True)
class FoldSpec:
    angle_deg: float
    direction: Literal["up", "down"]
    radius_mm: float | None = None

@dataclass(frozen=True, slots=True)
class Contour:
    id: str
    role: ContourRole
    closed: bool
    points: Points
    parent_id: str | None = None
    tags: tuple[str, ...] = ()
    segment_tags: tuple[str, ...] | None = None
    fold: FoldSpec | None = None

@dataclass(frozen=True, slots=True)
class Slice:
    id: str
    index: int
    contours: tuple[Contour, ...]
    frame_id: str | None = None          # непрозрачная ссылка для адаптера
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

### Инварианты контура

1. `points` — конечные числа; минимум 3 для `closed=True`, минимум 2 для
   открытого.
2. Замкнутый контур **не повторяет** первую точку в конце. Сегмент замыкания
   подразумевается: `p[n-1] → p[0]`.
3. `segment_tags`, если задан, имеет длину `n` для замкнутого и `n-1` для
   открытого контура. Тег описывает сегмент, начинающийся в точке `i`.
4. Соседние точки не совпадают ближе `min_segment_mm` (по умолчанию
   `1e-4 мм`); дубликаты устраняет `normalize`.
5. После `normalize`: внешние контуры — против часовой стрелки (CCW), отверстия —
   по часовой (CW). Ориентация важна для offset/kerf и для определения отверстий.
6. `parent_id` ссылается на контур того же среза. Если не задан, вложенность
   определяется чётностью (even-odd) в `normalize`; для `CUT` это обычно
   отверстие.
7. `role=SCORE` может быть открытым или замкнутым; `fold` имеет смысл только
   для `SCORE`.
8. `GUIDE` не участвует в экспорте реза, но может отображаться и использоваться
   как якорь.

> Почему не `Point`-объект: на срез в 50 000 точек dataclass на каждую точку
> даёт заметный overhead. Кортеж из двух float — компромисс между простотой,
> JSON и скоростью. Если понадобятся теги точек, они хранятся отдельным
> параллельным массивом, а не в точке.

## 2.3. Материал

```python
@dataclass(frozen=True, slots=True)
class MaterialProfile:
    id: str
    name: str
    thickness_mm: float
    min_bend_radius_mm: float
    max_bend_angle_deg: float
    min_segment_mm: float = 0.4
    kerf_mm: float = 0.0
    k_factor: float = 0.42
    extra: Mapping[str, float] = field(default_factory=dict)
```

| Поле | Смысл |
| --- | --- |
| `thickness_mm` | толщина листа/материала |
| `min_bend_radius_mm` | минимальный радиус изгиба по нейтральной оси |
| `max_bend_angle_deg` | максимальный угол сгиба для одной линии |
| `min_segment_mm` | минимальная допустимая длина сегмента |
| `kerf_mm` | ширина реза (для будущей компенсации) |
| `k_factor` | коэффициент нейтральной оси для расчёта развёртки |
| `extra` | расширяемые свойства (плотность, зерно, цвет и т.п.) |

Материал не хранит допуски обработки (сглаживание, упрощение) — это параметры
операций. Так один материал можно применять с разными пайплайнами.

## 2.4. Запрос

```python
class FailurePolicy(str, Enum):
    STRICT = "strict"          # любая ошибка → весь запрос ERROR
    PER_SLICE = "per_slice"    # упавший срез возвращается как есть
    BEST_EFFORT = "best_effort" # упавший этап пропускается, идём дальше

@dataclass(frozen=True, slots=True)
class TargetSelector:
    slice_ids: tuple[str, ...] | None = None
    slice_indices: tuple[int, ...] | None = None
    contour_ids: tuple[str, ...] | None = None
    roles: tuple[ContourRole, ...] | None = None
    tags_all: tuple[str, ...] = ()
    tags_any: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class OperationSpec:
    method: str
    params: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    target: TargetSelector | None = None   # None → target запроса
    label: str | None = None               # для GUI/логов, не влияет на расчёт

@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    schema_version: str
    protocol_version: str
    request_id: str
    units: str = "mm"              # v1: только "mm"
    material: MaterialProfile
    operations: tuple[OperationSpec, ...]
    slices: tuple[Slice, ...]
    targets: TargetSelector = TargetSelector()
    failure_policy: FailurePolicy = FailurePolicy.PER_SLICE
    options: RequestOptions = RequestOptions()
    limits: Limits = Limits()
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

`units` в v1 всегда `"mm"`. Любое другое значение — `E_UNITS`: перевод единиц
делает адаптер, а не движок.

`TargetSelector` — логическое **И** между заполненными полями. `tags_all` требует
все теги, `tags_any` — хотя бы один. Пустой селектор означает «все».

`RequestOptions`:

```python
@dataclass(frozen=True, slots=True)
class RequestOptions:
    return_unchanged: bool = True      # вернуть и нетронутые контуры
    include_metrics: bool = True
    include_point_tags: bool = False   # параллельные теги точек, если нужны
    normalize_winding: bool = True
    strict_unknown_fields: bool = True # False — игнорировать новые поля
    max_source_deviation_mm: float | None = None  # жёсткий предел, если нужен
```

`Limits` защищает от случайных гигантских запросов:

```python
@dataclass(frozen=True, slots=True)
class Limits:
    max_slices: int = 256
    max_points_per_contour: int = 200_000
    max_total_points: int = 1_000_000
    max_operations: int = 32
```

Запрос **самодостаточен**: в нём есть материал, операции и точки. Движок не
разрешает `preset_id`, не читает `project.json` и не обращается к файловой
системе. Это делает вызов воспроизводимым и позволяет гонять его по сети.

## 2.5. Результат

```python
class ResultStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"   # часть срезов/контуров не обработана
    ERROR = "error"       # запрос не выполнен целиком

@dataclass(frozen=True, slots=True)
class ContourResult:
    id: str
    source_id: str | None
    role: ContourRole
    closed: bool
    points: Points
    parent_id: str | None
    tags: tuple[str, ...]
    fold: FoldSpec | None
    changed: bool
    segment_tags: tuple[str, ...] | None
    metrics: ContourMetrics

@dataclass(frozen=True, slots=True)
class SliceResult:
    slice_id: str
    index: int
    frame_id: str | None
    changed: bool
    contours: tuple[ContourResult, ...]
    metrics: SliceMetrics
    diagnostics: tuple[Diagnostic, ...]

@dataclass(frozen=True, slots=True)
class ProcessingResult:
    schema_version: str
    protocol_version: str
    request_id: str
    status: ResultStatus
    engine: EngineInfo
    units: str                      # всегда "mm" в v1
    slices: tuple[SliceResult, ...]
    diagnostics: tuple[Diagnostic, ...]
    metrics: ResultMetrics
    metadata: Mapping[str, Any]     # эхо metadata запроса
```

`source_id` позволяет сопоставить выходной контур с входным, даже если движок
разбил или породил новый контур. Для новых контуров `source_id` — родитель, а
`id` — детерминированный суффикс.

Метрики (все необязательны, если `include_metrics=false`):

```python
@dataclass(frozen=True, slots=True)
class ContourMetrics:
    input_points: int
    output_points: int
    min_radius_mm: float | None
    max_turn_deg: float | None
    max_source_deviation_mm: float | None
    length_mm: float
    self_intersections: int

@dataclass(frozen=True, slots=True)
class SliceMetrics:
    input_points: int
    output_points: int
    input_contours: int
    output_contours: int
    stage_durations_ms: Mapping[str, float]  # только для профилирования

@dataclass(frozen=True, slots=True)
class ResultMetrics:
    slices_in: int
    slices_ok: int
    slices_failed: int
    points_in: int
    points_out: int
```

`min_radius_mm` — минимальный радиус кривизны по дискретной оценке; `None`, если
контур прямой или слишком короткий для оценки. `max_source_deviation_mm` —
максимальное расстояние от выходных точек до исходной полилинии (приближённо,
по сэмплам). Для филетов углов это значение может быть намеренно большим.

## 2.6. Диагностика и ошибки

```python
class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Severity
    code: ErrorCode
    message: str
    stage: str | None = None
    slice_id: str | None = None
    contour_id: str | None = None
    point_index: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
```

Коды (расширяемый enum):

| Код | Когда |
| --- | --- |
| `E_SCHEMA` | структура JSON не соответствует схеме |
| `E_PROTOCOL_VERSION` | несовместимая major-версия протокола |
| `E_UNKNOWN_FIELD` | неизвестное поле при `strict_unknown_fields` |
| `E_UNITS` | единицы не `mm` / несовместимый масштаб |
| `E_NON_FINITE` | `NaN`/`Infinity` в координатах или параметрах |
| `E_UNKNOWN_METHOD` | метода нет в реестре |
| `E_PARAM` | параметр вне диапазона/неверного типа |
| `E_TARGET_EMPTY` | селектор не нашёл ни одного контура |
| `E_GEOM_DEGENERATE` | слишком мало точек, нулевая длина, дубликаты |
| `E_GEOM_OPEN` | замкнутый контур не замкнут / открытый замкнут |
| `E_GEOM_SELF_INTERSECTION` | обнаружено самопересечение |
| `E_CONSTRAINT_UNSATISFIED` | радиус/угол/отклонение не выполнимы |
| `E_LIMIT_EXCEEDED` | превышен лимит точек/срезов/операций |
| `E_INTERNAL` | непредвиденная ошибка реализации |

Важно: `E_CONSTRAINT_UNSATISFIED` может быть `WARNING`, если политика разрешает
клампинг, и `ERROR`, если операция в режиме `error`. Код один, серьёзность
зависит от контекста.

`ValidationReport` (результат `validate`) содержит `ok`, список `Diagnostic`,
нормализованную копию запроса (без изменения исходного) и счётчики.

## 2.7. CoordinateFrame — собственность адаптера

Движок видит только `frame_id`. Полный кадр хранится в адаптере:

```python
@dataclass(frozen=True, slots=True)
class CoordinateFrame:
    id: str
    origin: Vec3
    u: Vec3          # единичный
    v: Vec3          # единичный
    # n = u × v, правая тройка

    def to_2d(self, p: Vec3) -> Point2:
        d = (p[0] - self.origin[0],
             p[1] - self.origin[1],
             p[2] - self.origin[2])
        return (dot(d, self.u), dot(d, self.v))

    def to_3d(self, q: Point2) -> Vec3:
        return (self.origin[0] + q[0] * self.u[0] + q[1] * self.v[0],
                self.origin[1] + q[0] * self.u[1] + q[1] * self.v[1],
                self.origin[2] + q[0] * self.u[2] + q[1] * self.v[2])
```

Правила построения кадра:

1. `origin` — точка плоскости, ближайшая к центроиду среза (детерминированно);
   если центроид не определён, берётся начало плоскости.
2. `u` — нормализованная проекция глобальной оси `u_hint` на плоскость. Если
   `|u_hint · n| > 0.99`, берётся запасная ось (`+Y` или `+Z`).
3. `v = n × u`; `n = u × v` — правая тройка.
4. Round-trip `to_3d(to_2d(p))` обязан укладываться в `1e-6 * scale`; адаптер
   проверяет это при подготовке и возвращает `E_FRAME` при нарушении.
5. При изменении плоскости среза кадр **пересоздаётся**; старый `frame_id`
   инвалидируется. Кеш результатов, ссылающийся на старый кадр, сбрасывается.
6. Кадры сериализуются отдельно от запроса (в проекте/рантайме) и не передаются
   в движок. В запросе остаётся только `frame_id` для эха.

Для радиальных срезов (плоскости вокруг оси) у каждого среза свой кадр: `origin`
лежит на оси, `u` направлен по радиусу, `v` — по оси/касательной. Конкретное
правило задаёт `slice_plan` в адаптере; движку это безразлично.

## 2.8. Полилиния как основной формат

Выход — плотная полилиния. Это:

* однозначно для лазерной резки и SVG/DXF;
* не зависит от типа кривых в хосте;
* легко валидируется и сравнивается.

Дополнительно можно вернуть `segment_tags` (например, `arc`, `line`, `fillet`)
для подсветки в хосте. В v1 **не** возвращаются параметрические формулы
(центр/радиус дуги, контрольные точки сплайна). Причина: разные хосты
представляют кривые по-разному, а формулы усложняют контракт и проверку
ограничений. Если понадобится, добавим необязательный блок
`curve_primitives` с версией схемы — без изменения основного массива точек.

## 2.9. JSON: примеры

* Полный запрос: [examples/request.example.json](examples/request.example.json)
* Полный результат: [examples/result.example.json](examples/result.example.json)
* Фрагмент среза:

```json
{
  "id": "s0",
  "index": 0,
  "frame_id": "f0",
  "metadata": { "layer_z_mm": 0.0 },
  "contours": [
    {
      "id": "s0.c0",
      "role": "cut",
      "closed": true,
      "parent_id": null,
      "points": [[0, 0], [60, 0], [60, 40], [0, 40]],
      "tags": ["outer"],
      "segment_tags": ["edge", "edge", "edge", "edge"]
    }
  ]
}
```

Правила JSON-кодека:

* snake_case, UTF-8, без комментариев (строгий JSON);
* отсутствующее необязательное поле = значение по умолчанию; `null` — только
  там, где он явно разрешён;
* неизвестные поля: ошибка при `strict_unknown_fields=true`, иначе
  игнорируются с предупреждением;
* канонический вид для хеширования: `sort_keys=True`, `separators=(",", ":")`,
  без пробелов, числа в обычной десятичной записи;
* большие массивы точек передаются как есть; сжатие/бинарный формат — будущая
  оптимизация, не v1.
