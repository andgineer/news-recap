# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      252 |      169 |     33% |126-273, 278-280, 283-290, 293-330, 336-361, 366-391, 395-402, 406-436, 440-485, 489-499, 503-505, 512-520, 524-556 |
| src/news\_recap/http/fetcher.py                          |       42 |       42 |      0% |      3-97 |
| src/news\_recap/http/html\_extractor.py                  |       29 |       18 |     38% |     35-74 |
| src/news\_recap/http/youtube\_extractor.py               |       48 |       31 |     35% |34-35, 41, 57-102 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |       33 |     38% |35-48, 59-65, 71-92, 98-99, 105 |
| src/news\_recap/ingestion/controllers.py                 |      154 |       91 |     41% |83-153, 156-206, 209-249, 252-287, 290-307, 317-321, 336-339, 344-354, 361, 369, 376-378, 387-390 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       38 |     42% |50-61, 71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |       60 |     19% |19-35, 41-46, 54-66, 76-83, 90-109, 122-135, 139, 146-153, 159-161 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       40 |     44% |23, 27-30, 40, 52, 55-72, 83-86, 89-91, 100-111, 117-121 |
| src/news\_recap/ingestion/language.py                    |       23 |       16 |     30% |     19-39 |
| src/news\_recap/ingestion/models.py                      |      161 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |       20 |     49% |36-50, 56-82, 93 |
| src/news\_recap/ingestion/repository.py                  |      487 |      419 |     14% |78-95, 101-102, 105-106, 114-168, 175-187, 190-192, 201-223, 232-262, 270-282, 307-317, 327-416, 431-466, 474-512, 521-583, 586-603, 606-618, 632-644, 652-662, 672-694, 702-712, 726-750, 759-779, 787-798, 801-812, 826-842, 854-884, 887-893, 932-962, 976-1006, 1014-1034, 1037-1089, 1104-1147, 1150-1168, 1171-1180, 1187-1215, 1230-1267, 1277-1295, 1309, 1321, 1325, 1329-1330, 1337-1339, 1347, 1368, 1372-1373, 1377-1379, 1383-1385, 1389 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       51 |       37 |     27% |25-26, 29-86, 90-99, 103, 107-109 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |       49 |     25% |38-41, 44-57, 72-129, 132-133 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        5 |     64% |22-23, 26-33 |
| src/news\_recap/ingestion/sources/base.py                |       31 |        4 |     87% |19, 46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      317 |     25% |45, 56, 70, 81, 91, 100, 165-169, 173-175, 179, 182-190, 197-222, 225-257, 260-317, 320-325, 334-339, 347-352, 355-380, 388-391, 399-405, 414-454, 458-460, 464-471, 480-503, 510-515, 519-543, 550-590, 594-632, 636-650, 654-663, 667-669, 673-678, 682-685, 689-690, 694-702, 706-719, 723-747, 751-754, 758-775, 785-799, 803-804 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        7 |     42% |     14-21 |
| src/news\_recap/ingestion/storage/common.py              |       36 |       22 |     39% |18, 24-27, 33-36, 42-59, 65-68, 72-76 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      362 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      301 |      292 |      3% |   50-1548 |
| src/news\_recap/orchestrator/backend/base.py             |       24 |        0 |    100% |           |
| src/news\_recap/orchestrator/backend/benchmark\_agent.py |       80 |       80 |      0% |     3-127 |
| src/news\_recap/orchestrator/backend/cli\_backend.py     |      165 |      142 |     14% |24-25, 32-84, 109-118, 144-198, 210-257, 261-283, 292-303, 307-318, 322, 337-380, 384-395 |
| src/news\_recap/orchestrator/backend/echo\_agent.py      |       19 |       19 |      0% |      3-42 |
| src/news\_recap/orchestrator/contracts.py                |      116 |       65 |     44% |71-72, 78-81, 87, 93-103, 109, 115-148, 154, 160-208, 214 |
| src/news\_recap/orchestrator/controllers.py              |      309 |      191 |     38% |176-198, 205-229, 239-255, 260-364, 367-379, 382-417, 420-423, 426-429, 434-501, 506-575, 580-630, 633-731, 735-737, 741, 745-754, 758-762, 775-785 |
| src/news\_recap/orchestrator/failure\_classifier.py      |       42 |       23 |     45% |67, 87-138, 147, 151-154 |
| src/news\_recap/orchestrator/intelligence.py             |      335 |      208 |     38% |149-161, 168-178, 181-222, 230-303, 310-400, 407-418, 425-434, 437-487, 490-531, 538-550, 555-568, 574-579, 607-614, 623-683, 693-724, 732-738, 748-803, 807, 815-816, 820-822, 826-832, 837-846, 850 |
| src/news\_recap/orchestrator/metrics.py                  |      236 |      177 |     25% |42-44, 93-235, 270-359, 371-397, 455-505, 509-515, 519-521, 525-527, 531-533, 537-543, 547-550, 556-565 |
| src/news\_recap/orchestrator/models.py                   |      292 |        0 |    100% |           |
| src/news\_recap/orchestrator/output\_fallback.py         |       89 |       77 |     13% |22-38, 53-67, 71-77, 85-122, 126-128, 132-134 |
| src/news\_recap/orchestrator/pricing.py                  |       51 |       40 |     22% |29-41, 45-57, 69-92 |
| src/news\_recap/orchestrator/repair.py                   |       14 |        5 |     64% |     26-39 |
| src/news\_recap/orchestrator/repository.py               |      635 |      558 |     12% |82-98, 106-107, 112-113, 116-129, 134-168, 173-229, 239-319, 324-338, 343-369, 381-464, 478-523, 538-585, 598-615, 620-683, 688-738, 748-758, 769-789, 800-817, 822-840, 848-859, 864-904, 909-972, 977-986, 1000-1030, 1040-1077, 1080-1089, 1101-1175, 1180-1211, 1220-1232, 1237-1266, 1275-1284, 1294-1315, 1320-1333, 1352-1379, 1384-1393, 1402-1422, 1427-1445, 1450-1467, 1478-1504, 1511-1533, 1538-1561, 1566-1598, 1603-1665, 1674-1680, 1690-1726, 1731-1740, 1765-1791, 1803-1810, 1819-1828, 1839-1892, 1895-1903, 1914-1936, 1948, 1964-1966, 1970-1972, 1976, 2010-2015, 2027-2033, 2070, 2084, 2097-2104, 2119-2142, 2161-2167 |
| src/news\_recap/orchestrator/routing.py                  |      104 |       70 |     33% |32, 56-88, 109-129, 148-164, 179-208, 220, 224, 228-230, 234-235 |
| src/news\_recap/orchestrator/sanitization.py             |       16 |        9 |     44% |     42-52 |
| src/news\_recap/orchestrator/services.py                 |       49 |       19 |     61% |50-52, 57-112, 115-131 |
| src/news\_recap/orchestrator/smoke.py                    |      111 |       81 |     27% |48-133, 137-156, 168-236, 240-255, 259-262 |
| src/news\_recap/orchestrator/usage.py                    |       91 |       67 |     26% |36-44, 56-74, 78-121, 132-141 |
| src/news\_recap/orchestrator/validator.py                |       80 |       62 |     22% |37-44, 53-76, 86-135, 161-237 |
| src/news\_recap/orchestrator/workdir.py                  |       55 |       44 |     20% |31, 46-120 |
| src/news\_recap/orchestrator/worker.py                   |      522 |      427 |     18% |126-143, 148-207, 224-252, 255-258, 261-263, 268-306, 320-332, 347-408, 426-465, 475-735, 749-813, 825-827, 831-857, 860-868, 882-890, 912-926, 936-954, 968-989, 1018-1026, 1032-1034, 1041-1047, 1050-1052, 1067-1092, 1095-1099, 1107-1112, 1119-1125, 1129-1131, 1135, 1143-1152, 1156-1174, 1178-1188, 1192-1195, 1199-1212, 1220-1236, 1245-1286, 1310-1335 |
| **TOTAL**                                                | **6231** | **4074** | **35%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fandgineer%2Fnews-recap%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.