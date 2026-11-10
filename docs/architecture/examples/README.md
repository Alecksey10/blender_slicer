# Примеры

| Файл | Что показывает |
| --- | --- |
| `project.example.json` | проект: план срезов, ссылки на пресеты, overrides, экспорт |
| `material.pla.example.json` | материал: толщина, радиусы, kerf, k-factor |
| `pipeline.smooth-cut.example.json` | полный пайплайн: fillet → smooth → simplify → densify |
| `request.example.json` | самодостаточный запрос к движку (2 среза, 4 контура) |
| `result.example.json` | результат: `partial`, скруглённый внешний контур, ошибка на тонкой стенке |
| `ui.schema.example.json` | декларативная GUI-схема, ссылающаяся на методы |
| `preview.slice0.svg` | предпросмотр «вход / выход / отклонённый срез» |

## Замечания

* `request.example.json` намеренно использует только `fillet_corners`, чтобы
  результат был обозримым. Полный пайплайн — в
  `pipeline.smooth-cut.example.json`; в метаданных запроса это отмечено как
  `fillet-only-demo`.
* Срез `s1` — тонкая стенка 1.2 мм. Запрошенный радиус 8 мм не помещается,
  поэтому срез возвращается без изменений с `E_CONSTRAINT_UNSATISFIED`, а
  общий статус — `partial`.
* `preview.slice0.svg` — статический пример того, что должен генерировать
  `slicer_preview`; его можно открыть в браузере или VS Code.
* В JSON нет комментариев: формат строгий, пояснения — в документах.

## Как посмотреть

```bash
# в браузере / VS Code
xdg-open preview.slice0.svg

# после реализации CLI
python -m slicer_preview --request request.example.json \
  --result result.example.json --out preview/
```
