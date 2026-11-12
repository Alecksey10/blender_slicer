# 3. API движка

## 3.1. Публичный фасад

```python
class Engine:
    """Чистый stateless-фасад. Один экземпляр можно переиспользовать."""

    def __init__(self, registry: MethodRegistry | None = None) -> None:
        """registry=None → встроенный набор методов."""

    def descriptor(self) -> EngineDescriptor: ...
    def descriptor_json(self) -> str: ...

    def validate(self, request: ProcessingRequest) -> ValidationReport: ...

    def process(self, request: ProcessingRequest) -> ProcessingResult: ...

    def process_json(self, payload: str | bytes) -> str:
        """Граница для RPC/CLI: JSON → JSON, доменные ошибки в результате."""
```

Свойства:

* `process` **не бросает** исключения для ошибок данных. Ошибка схемы, версии,
  параметра, геометрии возвращается как `ProcessingResult(status=ERROR|PARTIAL)`
  с диагностикой. Исключение `EngineBug` допустимо только для
  `E_INTERNAL`/ошибки программиста и должно быть задокументировано.
* `validate` не меняет запрос и не запускает операции. Он проверяет схему,
  версии, лимиты, params, цели, базовые геометрические инварианты.
* `descriptor` — статическая информация для GUI. Не зависит от проекта.
* Экземпляр `Engine` потокобезопасен при неизменном реестре.

### Пример вызова

```python
from slicer_protocol import json_codec
from slicer_engine import Engine

engine = Engine()

request = json_codec.load_request("examples/request.example.json")
report = engine.validate(request)
if not report.ok:
    for d in report.diagnostics:
        print(d.severity.value, d.code.value, d.message)
    raise SystemExit(1)

result = engine.process(request)
print(result.status.value)          # "partial" в примере
for s in result.slices:
    print(s.slice_id, s.changed, len(s.contours))
```

### JSON-граница

```python
result_json = engine.process_json(open("request.json", "rb").read())
```

Правила:

* вход — UTF-8 JSON; выход — канонический JSON;
* `request_id` эхом возвращается в результат;
* если JSON битый, возвращается `ProcessingResult` с `E_SCHEMA` и
  `request_id=""` (или тем, что удалось прочитать);
* `descriptor_json()` используется адаптером при старте.

Для внешнего процесса достаточно того же контракта: `stdin` → `process_json` →
`stdout`. Транспорт (pipe, localhost, in-process) не входит в движок.

## 3.2. Реестр методов

```python
class MethodRegistry:
    def register(self, method: Method) -> None: ...
    def get(self, name: str) -> Method | None: ...
    def descriptors(self) -> tuple[MethodDescriptor, ...]: ...
    def names(self) -> tuple[str, ...]: ...
```

`Method` — внутренний протокол; адаптерам он не нужен:

```python
class Method(Protocol):
    descriptor: MethodDescriptor
    scope: Literal["contour", "slice", "bundle"]

    def apply(
        self,
        inputs: MethodInput,
        params: Mapping[str, Any],
        ctx: MethodContext,
    ) -> MethodOutput: ...
```

* `scope="contour"` — метод обрабатывает контур независимо (большинство).
* `scope="slice"` — видит все контуры среза (например, проверка вложенности).
* `scope="bundle"` — видит все срезы (например, согласованная плотность).
* `MethodContext` содержит `diagnostics`, `limits`, `material`, `stage_name` и
  `emit()`; он не содержит глобального состояния.
* `MethodOutput` — новые контуры + диагностика + метрики этапа.

Встроенные методы v1:

| Имя | Scope | Назначение |
| --- | --- | --- |
| `normalize` | slice | встроенный, не указывается в `operations` |
| `resample` | contour | равномерная/адаптивная передискретизация |
| `simplify` | contour | Дуглас–Пекер с сохранением якорей |
| `smooth` | contour | Чаикин / ограниченный Лаплас |
| `fillet_corners` | contour | скругление углов дугой |
| `densify` | contour | адаптивное добавление точек |
| `limit_curvature` | contour | итеративное ограничение кривизны |
| `optimize_curve` | contour | глобальный МНК-фит: данные + энергия изгиба + радиус гиба |
| `local_recalc` | contour | пересчёт диапазона с якорями |
| `bend_check` | contour | проверка сгиба и bend allowance |
| `repair` | slice | дубликаты, замыкание, выбросы (экспериментально) |
| `validate` | slice | встроенный финальный, не указывается в `operations` |

`normalize` и `validate` всегда выполняются раннером. Их можно вызвать явно для
отладки, но в обычном конфиге они не нужны.

## 3.3. Дескриптор метода

Дескриптор — единственный источник правды для GUI: типы, defaults, границы,
единицы, группы, зависимости. GUI не дублирует эти значения.

```python
@dataclass(frozen=True, slots=True)
class Choice:
    value: str
    label: str

@dataclass(frozen=True, slots=True)
class Condition:
    param: str
    op: Literal["eq", "ne", "in", "gt", "lt"]
    value: Any

@dataclass(frozen=True, slots=True)
class ParamSpec:
    name: str
    type: Literal["float", "int", "bool", "string", "enum",
                  "point_list", "range", "json"]
    title: str
    description: str = ""
    default: Any = None
    required: bool = False
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: Literal["mm", "deg", "count", "ratio", ""] = ""
    choices: tuple[Choice, ...] = ()
    multiple: bool = False
    group: str = "general"
    order: int = 0
    advanced: bool = False
    visible_when: tuple[Condition, ...] = ()
    widget: str | None = None       # подсказка, не обязательство

@dataclass(frozen=True, slots=True)
class MethodDescriptor:
    name: str
    version: str
    title: str
    description: str
    scope: Literal["contour", "slice", "bundle"]
    params: tuple[ParamSpec, ...]
    stability: Literal["stable", "experimental", "deprecated"] = "stable"
    tags: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    name: str
    engine_version: str
    protocol_version: str
    schema_versions: tuple[str, ...]
    limits: Limits
    methods: tuple[MethodDescriptor, ...]
```

Пример `fillet_corners` в JSON (сокращённо):

```json
{
  "name": "fillet_corners",
  "version": "1.0",
  "title": "Corner fillets",
  "description": "Replaces corners sharper than min_turn_deg with tangent arcs.",
  "scope": "contour",
  "stability": "stable",
  "params": [
    {
      "name": "radius_mm",
      "type": "float",
      "title": "Radius",
      "default": 3.0,
      "min": 0.0,
      "max": 1000.0,
      "step": 0.1,
      "unit": "mm",
      "group": "geometry",
      "order": 10
    },
    {
      "name": "min_turn_deg",
      "type": "float",
      "title": "Min turn angle",
      "default": 20.0,
      "min": 0.0,
      "max": 179.0,
      "unit": "deg",
      "group": "geometry",
      "order": 20
    },
    {
      "name": "arc_segments",
      "type": "int",
      "title": "Arc segments",
      "default": 4,
      "min": 1,
      "max": 64,
      "unit": "count",
      "group": "quality",
      "order": 30
    },
    {
      "name": "mode",
      "type": "enum",
      "title": "If radius does not fit",
      "default": "clamp",
      "choices": [
        {"value": "clamp", "label": "Clamp and warn"},
        {"value": "error", "label": "Fail contour"},
        {"value": "skip", "label": "Leave corner as is"}
      ],
      "group": "policy",
      "order": 40
    }
  ]
}
```

Правила:

* `min`/`max` inclusive; `step` — только подсказка для UI.
* `visible_when` — декларативные условия, без `eval`. GUI-адаптер сам решает,
  как скрывать поле.
* `widget` — необязательная подсказка (`slider`, `select`, `textarea`), но
  адаптер может её игнорировать.
* `stability=experimental` методы не попадают в автоматически построенный GUI,
  если адаптер не включает их явно.

## 3.4. Валидация параметров

Порядок:

1. Структурная валидация JSON (`schema.py`): типы, обязательные поля,
   неизвестные поля.
2. Версии: `protocol_version`, `schema_version`.
3. Лимиты: число срезов/точек/операций.
4. Материал: положительные толщина/радиус, `0 <= k_factor <= 1`.
5. Операции: имя в реестре, params по `ParamSpec`, диапазоны, `enum`,
   `visible_when` (если GUI прислал скрытое поле — предупреждение, не ошибка).
6. Селекторы: существуют ли `slice_ids`/`contour_ids`; пустой результат —
   `E_TARGET_EMPTY` (обычно warning, если `allow_empty_targets=true`).
7. Геометрия: конечность, минимальное число точек, дубликаты, замыкание.

`ValidationReport`:

```python
@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    diagnostics: tuple[Diagnostic, ...]
    normalized: ProcessingRequest | None   # копия с defaults/нормализацией
    counts: Mapping[str, int]
```

Валидация **не** должна быть дороже обработки: проверка самопересечений —
отдельная опция `validate`-этапа и может быть O(n²).

## 3.5. Ошибки и политики

| Ситуация | `strict` | `per_slice` | `best_effort` |
| --- | --- | --- | --- |
| Ошибка в одном контуре | весь запрос ERROR | срез целиком возвращается как есть + ERROR | этап пропускается, срез продолжает со стадией до ошибки |
| Ошибка схемы/версии | ERROR | ERROR | ERROR |
| Неизвестный метод | ERROR | ERROR | ERROR |
| Ограничение невыполнимо | ERROR | пустой/исходный срез + ERROR | WARNING + ближайшее допустимое |

Важно: `per_slice` откатывает **весь срез**, а не отдельный контур, потому что
контуры среза связаны (отверстия, вложенность) и частично обработанный срез
может стать несогласованным. Если нужна контурная изоляция, это отдельная
политика `per_contour` в будущем.

## 3.6. CLI

```bash
# список методов и версий
python -m slicer_engine describe --pretty

# проверка запроса без обработки
python -m slicer_engine validate request.json

# обработка
python -m slicer_engine process request.json -o result.json

# предпросмотр (может вызывать process сам, если result не задан)
python -m slicer_preview --request request.json --result result.json --out preview/
```

CLI использует только `argparse`, `json`, `pathlib`, `sys`. Коды возврата:

| Код | Значение |
| --- | --- |
| 0 | успех (`ok`/`partial` с предупреждениями, если `--allow-partial`) |
| 2 | ошибка валидации/запроса |
| 3 | `status=error` |
| 4 | внутренняя ошибка |

## 3.7. Расширение

```python
class MyMethod:
    descriptor = MethodDescriptor(...)
    scope = "contour"

    def apply(self, inputs, params, ctx):
        ...

registry = MethodRegistry.builtins()
registry.register(MyMethod())
engine = Engine(registry=registry)
```

Ограничения:

* метод не импортирует хост и не читает файлы;
* метод не хранит состояние между вызовами;
* метод обязан вернуть диагностику вместо исключения для доменных ошибок;
* дескриптор должен быть сериализуемым (без callable в params);
* экспериментальные методы помечаются `stability="experimental"`.

## 3.8. Совместимость с существующим наброском

Текущие файлы `concept/engine/modules/...` — ранний набросок. Предлагаемое
отображение:

| Набросок | Куда переходит |
| --- | --- |
| `modules/datas/geometry.py` (`Point`, `Curve`, `ClosedCurve`) | `slicer_protocol/geometry.py` (`Point2`, `Contour`, `closed`) |
| `modules/schemas/methods_curve_schemas.py` | `ParamSpec`/`MethodDescriptor` + типизированные params метода |
| `modules/methods/optimize_curve.py` | `slicer_engine/methods/{simplify,smooth}.py` |

Отдельные классы `OptimizeDefaultCurveParameters` можно сохранить как удобные
типизированные обёртки, но источником defaults/валидации должен быть
дескриптор, иначе GUI и движок разъедутся.
