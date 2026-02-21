# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      293 |       73 |     75% |248, 250, 252, 258, 266, 268, 288, 301, 303, 305, 307, 311, 313, 315, 317, 319, 321, 323, 353, 360, 376, 378, 388-389, 393, 409, 424, 426, 434, 444, 456, 458, 477-482, 488, 498, 505, 512, 530-537, 549-572, 584-591 |
| src/news\_recap/http/fetcher.py                          |       42 |       20 |     52% |42-48, 58-81, 91, 94, 97 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        9 |     69% |47-49, 52-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       49 |       29 |     41% |    57-107 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        4 |     92% |41, 45-46, 75 |
| src/news\_recap/ingestion/controllers.py                 |      154 |       12 |     92% |143, 172, 194, 218, 241, 261, 293, 302, 338-339, 377, 388 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      161 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      487 |       59 |     88% |115, 144, 184, 209, 239, 255-260, 278, 307-317, 441, 464-466, 530-534, 602, 640, 746-748, 796, 827, 855, 878-881, 953-960, 1014-1034, 1265-1267, 1295, 1378 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       53 |        4 |     92% |30, 99-101 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       36 |        8 |     78% |24-27, 33-36 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      362 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      294 |       11 |     96% |742, 758, 929, 1099, 1148, 1174, 1239, 1362, 1404, 1434, 1510 |
| src/news\_recap/orchestrator/backend/base.py             |       24 |        0 |    100% |           |
| src/news\_recap/orchestrator/backend/benchmark\_agent.py |       88 |       88 |      0% |     3-149 |
| src/news\_recap/orchestrator/backend/cli\_backend.py     |      165 |       51 |     69% |24-25, 77-83, 111, 114, 146-197, 209, 222, 233-234, 241, 261-262, 281, 283, 287, 290, 301-302, 304, 376-377, 380-385 |
| src/news\_recap/orchestrator/backend/echo\_agent.py      |       24 |       24 |      0% |      3-48 |
| src/news\_recap/orchestrator/contracts.py                |      116 |       17 |     85% |80, 98, 100, 102, 118, 123, 130, 132, 134, 136, 138, 154, 173, 177, 191, 207-208 |
| src/news\_recap/orchestrator/controllers.py              |      309 |       27 |     91% |387, 420-423, 426-429, 437-440, 459, 490, 511, 588-591, 637-638, 646, 655, 720, 736, 754 |
| src/news\_recap/orchestrator/failure\_classifier.py      |       42 |        2 |     95% |  100, 127 |
| src/news\_recap/orchestrator/intelligence.py             |      335 |       88 |     74% |168-178, 193-195, 237, 310-400, 407-418, 425-434, 437-487, 538-550, 555-568, 574-579, 637, 641-644, 646-658, 706, 735, 822 |
| src/news\_recap/orchestrator/metrics.py                  |      236 |       60 |     75% |42-44, 98-102, 128-131, 149-157, 162, 166-168, 173, 227, 229, 231-233, 304-306, 316, 333, 352, 382, 460, 467-468, 475-476, 485, 499, 505, 509-515, 527, 539-543, 549, 557 |
| src/news\_recap/orchestrator/models.py                   |      293 |        0 |    100% |           |
| src/news\_recap/orchestrator/output\_fallback.py         |       89 |       28 |     69% |24, 32-38, 55, 63-67, 76, 87, 90, 95, 98, 105, 107, 111, 115, 119, 127, 132-134 |
| src/news\_recap/orchestrator/pricing.py                  |       51 |        5 |     90% |41, 76, 79, 84-85 |
| src/news\_recap/orchestrator/repair.py                   |       14 |       14 |      0% |      3-39 |
| src/news\_recap/orchestrator/repository.py               |      635 |      119 |     81% |214-215, 240, 271, 280, 302, 324-338, 358-359, 480, 606, 629, 663-670, 697, 815, 830, 925, 928, 930, 1020, 1022, 1024, 1026, 1045, 1047, 1069, 1140, 1162, 1204-1209, 1239-1268, 1277-1286, 1416-1424, 1452-1469, 1490, 1493, 1548-1563, 1593-1594, 1596, 1605-1667, 1700, 1776, 1785, 1812, 1828, 1862-1871, 1897-1905, 1967, 2033-2034, 2086, 2104-2105, 2126-2127, 2132-2133, 2165, 2168 |
| src/news\_recap/orchestrator/routing.py                  |      104 |       16 |     85% |65, 83, 85, 123, 128, 153, 188, 190, 193, 195, 198, 200, 202, 204, 206, 235 |
| src/news\_recap/orchestrator/sanitization.py             |       16 |        1 |     94% |        52 |
| src/news\_recap/orchestrator/services.py                 |       49 |        0 |    100% |           |
| src/news\_recap/orchestrator/smoke.py                    |      111 |       41 |     63% |72-89, 92-105, 146-149, 156, 176-192, 208, 211, 220-223, 228, 230, 240-255, 262 |
| src/news\_recap/orchestrator/usage.py                    |       91 |        3 |     97% |137, 140-141 |
| src/news\_recap/orchestrator/workdir.py                  |       55 |        0 |    100% |           |
| src/news\_recap/orchestrator/worker.py                   |      493 |      107 |     78% |148-149, 178-180, 188-194, 227, 229, 243-244, 250, 255, 260, 271-272, 291, 318-330, 346, 386-392, 424-463, 474, 476, 557-558, 561-573, 677-679, 684-685, 691-695, 715, 717, 737, 739, 788-806, 894, 899, 903, 973, 976, 986, 989, 994-996, 1008-1017, 1028, 1031, 1035, 1044, 1047, 1049, 1052-1053, 1059, 1069, 1072, 1074, 1090, 1116, 1123-1126, 1134, 1191, 1196 |
| src/news\_recap/recap/controllers.py                     |       86 |       59 |     31% |45-106, 110-128, 133-143 |
| src/news\_recap/recap/prefect\_flow.py                   |      164 |      115 |     30% |62-68, 72, 98-158, 169-201, 228, 240, 243, 254-278, 289-314, 324-331, 352-403 |
| src/news\_recap/recap/prompts.py                         |        9 |        0 |    100% |           |
| src/news\_recap/recap/resource\_loader.py                |       43 |       21 |     51% |39-41, 46-48, 51-59, 68-90, 99-100, 103, 106 |
| src/news\_recap/recap/runner.py                          |      369 |      204 |     45% |57-64, 131-141, 146-155, 158-163, 166-196, 202-208, 215-216, 229-230, 242-243, 256-257, 265, 268-274, 278-279, 327-483, 498-583, 593-613, 621-661, 665, 686-690, 804, 842 |
| src/news\_recap/recap/schemas.py                         |        8 |        0 |    100% |           |
| **TOTAL**                                                | **6852** | **1492** | **78%** |           |


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