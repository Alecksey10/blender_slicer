# Требования к конечным средам (хостам)

Статус: черновик. Версия 0.1, 2026-11-11.

Документ описывает, что должна предоставить среда, чтобы подключить движок
срезов, и что остаётся на стороне ядра. Он дополняет
`docs/requirements/api_environment.md` (серверная среда) и
`docs/plan/README.md` (порядок работ).

## 1. Общая модель

Ядро работает только с **2D-контурами в миллиметрах**. Хост отвечает за
3D: меш, плоскости, локальные кадры и отображение. Один и тот же запрос
`ProcessingRequest` должен давать одинаковый `ProcessingResult` в Blender,
FreeCAD, CLI и по HTTP.

```
mesh (host)
  -> plane intersection (host)
  -> 3D segments (host)
  -> chain into contours (host)
  -> CoordinateFrame.to_2d (host)
  -> ProcessingRequest (host -> engine)
  -> ProcessingResult (engine)
  -> CoordinateFrame.to_3d + display (host)
```

## 2. Обязательный контракт хоста

| Метод | Вход | Выход | Примечание |
| --- | --- | --- | --- |
| `slice_mesh(plan)` | `SlicePlan` | `list[Slice]`, `dict[frame_id, CoordinateFrame]` | нарезка меша и перевод в 2D |
| `show_layers(layers)` | `list[SliceLayer]` | — | рисование результата |
| `show_contacts(contacts)` | `list[ContactPoint]` | — | маркеры контактов |
| `clear_visuals()` | — | — | очистка коллекций/объектов |

Дополнительно адаптер обязан:

* хранить `SliceLayer`, `CoordinateFrame` и ревизию в памяти сессии;
* строить `SlicePlan` из своих настроек;
* собирать `ProcessingRequest` с материалом, операциями, лимитами и
  политикой ошибок;
* вызывать `AppController` (генерация, обработка, контакты, видимость);
* публиковать события `TOPIC_*`, чтобы панель обновлялась;
* не импортировать внутренние модули движка, кроме публичных фасадов.

## 3. Единицы, кадры и данные

* Вход ядра: `Point2 = (x, y)` в мм; углы в градусах на границе, радианы
  внутри.
* `CoordinateFrame` создаётся хостом: нормаль, `u`-вектор, начало координат, масштаб
  `unit_scale_mm`.
* `frame.to_2d(p3)` и `frame.to_3d((x, y))` — единственные точки перевода.
* Контуры: `closed=True/False`, роль `cut/score/guide`.
* `Slice.metadata` — свободный словарь; хост кладёт туда `slice_mode`,
  `offset_mm`, `spacing_mm`, `angle_deg`, `cut_offset_mm`.
* Ошибки не бросаются через границу: хост читает `result.status` и
  `diagnostics`.

## 4. Blender

| Параметр | Требование |
| --- | --- |
| Версия | Blender 3.6+ / 4.x, Python из поставки |
| Модули | `bpy`, `mathutils`, `bpy_extras` |
| Меш | `evaluated_get(depsgraph).to_mesh()`, мировые координаты |
| Нарезка | `adapters/blender/slicing.py` |
| Визуализация | кривые в коллекции `Slice Engine`, маркеры контактов |
| UI | `bpy.types.Panel`, схема `ui_schema`, операторы |
| Состояние | `RUNTIME` + `Scene.slicer_settings` |
| Headless | `blender --background --python ...` |

Blender-адаптер — эталон: его `slicing.py` и `visualization.py` задают
поведение, которое должен повторить FreeCAD.

## 5. FreeCAD

### 5.1. Среда

| Параметр | Требование |
| --- | --- |
| Версия | FreeCAD 0.21+ или 1.0+ |
| Python | из поставки FreeCAD (3.8/3.10+ в зависимости от сборки) |
| Модули | `FreeCAD`, `Part`, `Mesh`, `Draft` (опционально), `PySide`/`PySide2` для панели |
| Ядро | чистый Python-пакет `blender_slicer` без `bpy` |
| Headless | `freecadcmd` / `FreeCADCmd` для тестов и пакетной обработки |

Ядро импортируется как обычный Python-пакет. Если `blender_slicer`
установлен в `Mod/` FreeCAD, адаптер лежит в
`blender_slicer/adapters/freecad/`; альтернативно — отдельный addon,
который добавляет путь к пакету.

### 5.2. Получение меша

1. Взять активный объект (`Gui.Selection.getSelection()` или
   `App.ActiveDocument`).
2. Проверить `obj.Shape` и `obj.Shape.Faces`.
3. Тесселировать: `vertices, facets = shape.tessellate(0.1)`.
   Допуск тесселяции задаётся в мм и должен быть не грубее `0.1` мм для
   типовых деталей.
4. Применить глобальное размещение: `obj.Shape.Placement.multVec(v)` или
   `obj.getGlobalPlacement()`.
5. Собрать треугольники `(a, b, c)` и передать в общий слой нарезки.

Требование: слой нарезки FreeCAD не копирует `_plane_segments` и
`chain_segments` из Blender, а использует **общий** модуль
`adapters/base/meshing.py` (появляется на этапе P3 плана). До этого
допускается временная реализация с теми же тестами.

### 5.3. Плоскости и кадры

* Ось и режим берутся из `SlicePlan` (`axis`, `mode`, `count`,
  `spacing_mm`, `auto_spacing`, `centered`, `offset_mm`).
* Для автошага протяжённость считается по проекциям вершин на нормаль,
  ровно как в Blender: `extent_mm / count`, равные поля по краям.
* Кадр: `CoordinateFrame` из `spatial.frames.make_frame`; для FreeCAD
  удобно хранить `FreeCAD.Placement` рядом с кадром, но ядру он не нужен.
* Перевод: `frame.to_2d(FreeCAD.Vector)` и `frame.to_3d((x, y))`.

### 5.4. Результат и отображение

* Замкнутые контуры — `Part.makePolygon(points3d + [first])` или
  `Draft.make_wire`; открытые — `Part.makePolygon(points3d)`.
* Один `App::FeaturePython`/`Part::Feature` на слой; имя содержит
  `layer.id`, `slice.index`, `frame_id`.
* Цвет — как в Blender: `cut` основной, `score` светлее, `guide` серый.
* Контакты — маленькие `Part::Feature` (октаэдр/сфера) с цветом по
  `contact.kind`; радиус `max(contact_marker_mm, 0.005 * габарит)`.
* Видимость слоя — `ViewObject.Visibility`; очистка — удаление
  `DocumentObject` и временных `Shape`.

### 5.5. UI и настройки

* Панель — Qt (`PySide`) или `Draft`-панель; поля строятся из
  `adapters.base.ui.SECTIONS`, чтобы не дублировать подписи и видимость.
* Настройки — `App::PropertyString/Integer/Float/Bool` в `FeaturePython`
  или отдельный `App::PropertyGroup`; сериализация — общий
  `settings_io`-подобный слой с той же таблицей полей.
* Кнопки: Generate, Process, Find Contacts, Frame Contacts, Clear,
  Export/Import Settings, Export Slices.
* Язык — из настроек FreeCAD/Qt; каталог `i18n` общий.

### 5.6. Состояние и события

* `RUNTIME` (слои, кадры, ревизия) — модульный синглтон, как в Blender.
* Изменение настроек увеличивает `revision` и помечает результат stale.
* После обработки панель обновляется без перезапуска.
* `build_curves=False` не должен отключать маркеры контактов.

### 5.7. Ограничения FreeCAD

* Нельзя импортировать `bpy`/`mathutils`; использовать `FreeCAD.Vector`
  и `FreeCAD.Placement`.
* Нельзя полагаться на `numpy`, `shapely`, `trimesh`; ядро и адаптер —
  только стандартная библиотека + API FreeCAD.
* Тесселяция и булевы операции FreeCAD могут давать другие точки, чем
  Blender; сравнивать результаты нужно по допуску, а не побитно.
* Долгие операции — в `Document.openTransaction()` с `commitTransaction()`,
  чтобы пользователь мог отменить.
* Headless-тесты не должны требовать GUI; визуализацию проверять
  отдельно, контракт — через фейковый хост.

### 5.8. Чек-лист приёмки FreeCAD-адаптера

1. Куб режется по X/Y/Z; число срезов и шаг совпадают с планом.
2. `auto_spacing` даёт тот же шаг, что Blender на том же меше.
3. Филлет, smooth, simplify, offset, shrink, trim, cut thin работают без
   изменений ядра.
4. Маркеры контактов видимы и не зависят от `build_curves`.
5. Слои можно скрывать/удалять; повторная генерация не плодит объекты.
6. Ошибка одного среза не ломает остальные при `per_slice`.
7. Экспорт/импорт настроек сохраняет все поля.
8. `freecadcmd`-тест проходит без GUI.

## 6. CLI и HTTP API

* CLI: `python3 -m blender_slicer.engine.cli` — без GUI, только JSON.
* HTTP: см. `docs/requirements/api_environment.md`; сервер не импортирует
  хостовые модули и не режет 3D.
* Оба используют один и тот же `Engine` и `protocol/json_codec.py`.

## 7. Матрица совместимости

| Возможность | Blender | FreeCAD | CLI | API |
| --- | --- | --- | --- | --- |
| 3D-нарезка меша | да | да | нет (вход 2D) | нет (вход 2D) |
| автошаг | да | да | да (в плане) | да |
| все методы движка | да | да | да | да |
| контакты | да | да | да (расчёт) | да (расчёт) |
| визуализация | кривые | Part/Draft | SVG | — |
| UI | bpy-панель | Qt/Draft | — | — |
| headless | да | да | да | да |

## 8. Правила против дублирования

1. Формулы и допуски — только в `protocol/geometry`.
2. Нарезка меша — один общий модуль; адаптер даёт только треугольники.
3. Поля настроек — одна таблица (этап P2), адаптер только отображает.
4. Диагностика — общий `emit_warnings`.
5. Новый адаптер не копирует `adapter.py` Blender: он использует
   `adapters/base/controller.py`, `layers.py`, `runtime.py`, `plan.py`.

## 9. Критерии приёмки среды

1. Ядро импортируется без хостовых библиотек.
2. Адаптер реализует четыре метода контракта и проходит общий
   contract-тест.
3. Один и тот же `ProcessingRequest` даёт одинаковый результат в двух
   хостах в пределах допуска тесселяции.
4. Нет импортов `bpy`/`FreeCAD` из `protocol`, `engine`, `spatial`.
5. Все настройки доступны в UI, экспорте и импорте.
