> **Устарело (0.2.x).** Описывает прежнюю структуру `core/` + `host/`.
> Актуальное описание — [README.md](README.md) и
> [docs/architecture/](docs/architecture/README.md).

# Slice Engine — плагин срезов для Blender

Плагин строит двумерные срезы меша, обрабатывает их независимым вычислительным
движком (геометрия, ограничения материала, сглаживание) и строит результат
обратно в сцене в виде кривых. Движок не знает о Blender: он получает только
2D-точки в миллиметрах и возвращает новые 2D-точки, поэтому его можно прогонять
и тестировать обычным Python.

## Установка

1. Скопировать папку `blender_slicer` из этого репозитория в zip-архив
   (папка должна быть корнем архива, внутри — `__init__.py`, `core/`, `host/`).
2. Blender → `Edit → Preferences → Add-ons → Install…` → выбрать архив.
3. Включить аддон «Slice Engine» (категория `Object`).
4. В 3D-вью открыть боковую панель (`N`) и вкладку **Slice**.

Требуется Blender 4.0 или новее; аддон проверяет версию при регистрации.

## Проверка сборки в Blender

Архив для установки собирается из дерева проекта:

```bash
python3 tools/build_addon_zip.py          # -> dist/blender_slicer-0.2.1.zip
```

### Автоматически (headless)

```bash
# 1. проверка самого архива — тот же путь, что и «Install from Disk»
blender --background --factory-startup --python-exit-code 1 \
    --python tools/blender_smoke.py -- --zip dist/blender_slicer-0.2.1.zip

# 2. проверка рабочего дерева без установки в пользовательский каталог
blender --background --factory-startup --python-exit-code 1 \
    --python tools/blender_smoke.py -- --source
```

Скрипт печатает `PASS`/`FAIL` по каждому пункту и в конце `RESULT: N/N checks
passed`; при любом провале Blender завершается с кодом 1. Что проверяется:

* регистрация аддона, свойства `Scene.slicer_settings` и его RNA;
* все поля GUI-схемы и все поля экспорта настроек действительно стали
  RNA-свойствами (именно это ломается при `from __future__ import annotations`);
* зарегистрированы все операторы и все три панели;
* куб → 3 плоских среза → пайплайн → кривые в коллекции `Slice Engine`;
* радиальный веер плоскостей;
* невыполнимое скругление (`fillet_mode = error`) даёт диагностику
  `E_CONSTRAINT_UNSATISFIED`, а не падение;
* экспорт/импорт рецепта JSON, `Clear`, выключение аддона.

`--zip` ставит архив в пользовательский каталог аддонов (как ручная установка);
добавьте `--keep`, чтобы оставить его включённым после прогона, иначе скрипт
удалит установленный аддон.

### Вручную в GUI

1. `Edit → Preferences → Add-ons → Install…` → выбрать архив → включить
   «Slice Engine». В консоли не должно быть ни трейсбека, ни предупреждений
   вида `class ... contains a property which should be an annotation`.
2. Выделить куб, `N` → вкладка **Slice**: панель показывает «Ready», сверху
   кнопки Actions, ниже — сворачиваемые секции (Source и Slice plan открыты,
   остальные разворачиваются кликом по заголовку).
3. `Source mesh = Cube`, `1 BU in mm = 1000`, `Count = 3`, `Spacing = 100` →
   **Generate Slices**: появляются три кривые в коллекции `Slice Engine`, а
   статус в панели обновляется сразу, без движения мыши.
4. **Process Slices**: статус `OK - 3/3 slices`, число точек растёт (скругления
   и densify), вьюпорт показывает скруглённые квадраты.
5. Поставить `Radius = 900` и `If radius does not fit = Fail slice` → **Process
   Slices**: статус `PARTIAL`/`ERROR`, в панели Report видна причина, геометрия
   не изменилась.
6. Изменить любой параметр после обработки → статус «Settings changed» и
   подсказка «Result is stale».
7. **Export Settings** → JSON, изменить радиус, **Import Settings** → радиус
   восстановлен, предупреждений нет.
8. **Clear** → коллекция очищена, статус «Cleared».
9. Выключить аддон в Preferences → `Scene.slicer_settings` исчезает, ошибок в
   консоли нет.

## Как пользоваться

Вкладка **Slice**: сверху статус и кнопки (`Run`, `Generate Slices`, `Process Slices`,
`Clear`, `Export/Import Settings`), ниже — сворачиваемые подпанели настроек
(`Source` и `Slice plan` раскрыты по умолчанию, остальные открываются по клику).

1. **Source** — выбрать меш и задать, сколько миллиметров в одной единице
   Blender (по умолчанию 1 BU = 1000 мм).
2. **Slice plan** — режим `Planar stack` (параллельные плоскости по оси X/Y/Z)
   или `Radial fan` (веер плоскостей вокруг оси, с диапазоном углов), количество,
   шаг, смещение, центрирование, смещение центра срезов.
3. **Material** — толщина листа, минимальный радиус гиба, максимальный угол гиба,
   минимальная длина сегмента, керф, K-фактор.
4. **Операции** — `Fillet corners`, `Smooth`, `Simplify`, `Densify`, `Resample`,
   `Limit curvature`. Порядок фиксирован:
   `fillet → smooth → simplify → densify → resample → limit curvature`.
   Каждая операция включается/выключается галочкой, параметры — в её блоке.
5. **Actions** (вверху панели):
   * `Run` — generate + process одним нажатием;
   * `Generate Slices` — пересечение меша с плоскостями, построение исходных
     кривых;
   * `Process Slices` — прогон пайплайна по уже сгенерированным срезам;
   * `Clear` — удалить кривые и результат;
   * `Export/Import Settings` — сохранить или загрузить рецепт срезов в JSON.

Панель **Report** показывает статус, число срезов/точек, ошибки и предупреждения
движка; кнопка `Show Report` открывает полный список диагностик.

Результат складывается в коллекцию `Slice Engine` (по объекту `Slice_NNN` на
срез), роли контуров раскрашены материалами `SliceCut` / `SliceScore` /
`SliceGuide`.

## Архитектура

```
blender_slicer/
  __init__.py          bl_info, register/unregister аддона
  core/                движок: без bpy, только стандартная библиотека
    types.py           контракт данных: Slice, Contour, MaterialProfile, request/result
    geometry.py        2D-геометрия: длина, радиус, кривизна, самопересечения,
                       simplify, resample, densify, chaikin/laplacian, fillet, доля гиба
    descriptors.py     декларативные параметры методов (для GUI и валидации)
    registry.py        реестр методов + валидация параметров
    methods/           normalize, fillet, smooth, simplify, densify, resample,
                       limit_curvature, bend_check
    engine.py          фасад: validate / process, политики ошибок, метрики
    frames.py          CoordinateFrame: 3D <-> 2D
    json_codec.py      JSON-контракт запроса и результата
  host/                слой Blender: единственное место, где импортируется bpy
    slicing.py         пересечение меша с плоскостями, сборка контуров
    adapter.py         настройки -> запрос -> движок -> визуализация, события
    properties.py      свойства сцены (все параметры GUI)
    ui_schema.py       декларативная раскладка панели
    panels.py          панели N-вкладки
    operators.py       операторы (generate/process/run/clear/report/import/export)
    visualization.py   построение кривых результата
    events.py          EventBus и темы
    runtime.py         состояние выполнения (срезы, кадры, результат)
    settings_io.py     экспорт/импорт рецепта в JSON
tests/                 headless-проверки (bpy замокан)
```

Правило зависимостей: `core` не импортирует `host`; `host` использует только
публичный фасад `core`. Все координаты движка — миллиметры, углы — градусы
(внутри геометрии — радианы).

## Геометрические методы

| Метод | Что делает | Ключевые параметры |
| --- | --- | --- |
| `fillet_corners` | заменяет углы касательными дугами | `radius_mm`, `min_turn_deg`, `arc_segments`, `chord_tolerance_mm`, `mode` (`clamp`/`error`/`skip`), `check_material` |
| `smooth` | Chaikin или ограниченный Laplacian | `algorithm`, `iterations`, `preserve_corners_deg`, `max_deviation_mm`, `weight` |
| `simplify` | Дуглас—Пекер с сохранением углов | `tolerance_mm`, `preserve_corners_deg` |
| `densify` | добавляет точки по шагу/углу/хорде | `max_spacing_mm`, `max_angle_step_deg`, `chord_tolerance_mm` |
| `resample` | равномерная или адаптивная переразбивка | `spacing_mm`, `adaptive`, `min_spacing_mm`, `chord_tolerance_mm` |
| `limit_curvature` | сглаживает вершины до минимального радиуса | `use_material_min_radius`, `min_radius_mm`, `max_iterations`, `weight`, `strict` |
| `bend_check` | проверка линии сгиба и bend allowance | `mode`, `report_allowance` |

Каждый метод описывает себя через `MethodDescriptor`/`ParamSpec`: имя, тип,
значение по умолчанию, диапазон, единицы, варианты. По этому описанию строится
GUI и выполняется валидация параметров до запуска расчёта.

## Проверка и тесты

```bash
python3 -m unittest discover -s tests -t . -v
```

Проверки не требуют Blender: `tests/fake_blender.py` подменяет `bpy` и
`mathutils` минимальными заглушками, поэтому тестируются и слой хоста
(пересечение меша с плоскостями, сборка контуров, маппинг настроек в операции,
регистрация аддона), и сам движок.

Покрыто:

* `tests/test_geometry.py` — аналитические случаи филета (дуга, clamp/error/skip),
  Chaikin/Laplacian с якорями, Дуглас—Пекер, resample/densify, ограничение
  кривизны, bend allowance, самопересечения (сверка с эталонным O(n²)-подсчётом);
* `tests/test_frames.py` — ортонормальность кадра, round-trip 3D→2D→3D,
  проецирование на плоскость, единицы мм;
* `tests/test_contract.py` — JSON round-trip, устойчивость к лишним полям,
  отсутствие NaN/Infinity, детерминизм на примере из `concept/`;
* `tests/test_engine.py` — валидация контракта и параметров, лимиты, метрики,
  селекторы, политики `strict` / `per_slice` / `best_effort`, изоляция сбоев;
* `tests/test_host.py` — куб → срезы → движок → 3D, радиальный режим,
  соответствие операций дескрипторам, регистрация и события.

## Расширение

* Новый геометрический метод: класс в `core/methods/` с `descriptor` и
  `apply_contour`, добавить в `MethodRegistry.builtins()`, затем — блок в
  `host/properties.py`, `host/ui_schema.py`, `host/settings_io.py` и
  `adapter.operations_from_settings`.
* Новая GUI-среда: реализовать адаптер, который собирает формы из
  `Engine.descriptor()` и `host/ui_schema.SECTIONS` и передаёт 2D-точки в
  `Engine.process`.
