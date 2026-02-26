# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      263 |       47 |     82% |221, 225, 227, 233, 239, 242, 246, 261, 263, 265, 267, 271, 273, 301, 308, 324, 326, 336-337, 341, 384-401, 410, 412, 431-436, 442, 452, 459, 466 |
| src/news\_recap/http/fetcher.py                          |       42 |        4 |     90% |47, 92, 95, 98 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        7 |     76% |47-49, 60-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       74 |       45 |     39% |38, 42-43, 67, 81-92, 101-126, 149-170 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        1 |     98% |        75 |
| src/news\_recap/ingestion/controllers.py                 |      120 |        8 |     93% |138, 160, 184, 207, 227, 265-266, 302 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      191 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      329 |       28 |     91% |97, 139, 212, 226, 228, 238-243, 256, 282-289, 342, 420, 582, 600, 606, 709-712 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       49 |        3 |     94% |    99-101 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/main.py                                  |       61 |        1 |     98% |       301 |
| src/news\_recap/recap/agents/ai\_agent.py                |      101 |       80 |     21% |54-94, 99-109, 125-171, 199-213, 238-289 |
| src/news\_recap/recap/agents/benchmark.py                |       88 |       88 |      0% |     3-149 |
| src/news\_recap/recap/agents/echo.py                     |       40 |       40 |      0% |     19-90 |
| src/news\_recap/recap/agents/routing.py                  |       94 |       17 |     82% |40, 52-60, 88, 114, 119, 143, 175, 177, 180, 182, 184, 186, 188 |
| src/news\_recap/recap/agents/subprocess.py               |      109 |       39 |     64% |22-23, 57, 68, 80-81, 88, 105-106, 125, 127, 131, 134, 145-146, 148, 172-205, 209-220 |
| src/news\_recap/recap/contracts.py                       |      116 |       43 |     63% |80, 93-103, 115-148, 154, 173, 177, 191, 207-208 |
| src/news\_recap/recap/flow.py                            |       65 |       42 |     35% |41-44, 51-52, 66-127 |
| src/news\_recap/recap/launcher.py                        |       81 |       51 |     37% |29, 64-95, 109-118, 130-191 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       52 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      123 |       13 |     89% |85, 174-180, 184-186, 208, 219, 265, 274-275, 278, 281 |
| src/news\_recap/recap/models.py                          |       47 |        8 |     83% |24-29, 32, 41 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      155 |       36 |     77% |36-43, 48, 77-80, 93-96, 112-134, 145-151, 174, 180-181, 195, 244, 255, 290 |
| src/news\_recap/recap/storage/schemas.py                 |        1 |        1 |      0% |         7 |
| src/news\_recap/recap/storage/workdir.py                 |       55 |        0 |    100% |           |
| src/news\_recap/recap/tasks/base.py                      |       52 |       15 |     71% |65, 88-104, 107 |
| src/news\_recap/recap/tasks/classify.py                  |      154 |       21 |     86% |133, 139, 219-230, 240, 247-248, 253, 293-295 |
| src/news\_recap/recap/tasks/enrich.py                    |      165 |       16 |     90% |129-130, 167, 196-197, 260-265, 285-289, 300, 313-314, 355 |
| src/news\_recap/recap/tasks/load\_resources.py           |       57 |        6 |     89% |44, 86-87, 93-95 |
| src/news\_recap/recap/tasks/map\_blocks.py               |      146 |        8 |     95% |152, 218, 232-234, 250-251, 297 |
| src/news\_recap/recap/tasks/parallel.py                  |       40 |        9 |     78% |79-86, 104 |
| src/news\_recap/recap/tasks/prompts.py                   |        5 |        0 |    100% |           |
| src/news\_recap/recap/tasks/reduce\_blocks.py            |       98 |       35 |     64% |62-70, 83-84, 90, 97, 100-101, 130-171 |
| src/news\_recap/storage/io.py                            |       42 |        6 |     86% |33-36, 59, 73 |
| **TOTAL**                                                | **3905** |  **891** | **77%** |           |


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