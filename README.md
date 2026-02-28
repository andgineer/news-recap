# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      266 |       47 |     82% |226, 230, 232, 238, 244, 247, 251, 266, 268, 270, 272, 276, 278, 306, 313, 329, 331, 341-342, 346, 398-415, 424, 426, 445-450, 456, 466, 473, 480 |
| src/news\_recap/http/fetcher.py                          |       42 |        4 |     90% |47, 92, 95, 98 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        7 |     76% |47-49, 60-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       94 |       15 |     84% |116-120, 140, 144, 158, 160-165, 190, 198 |
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
| src/news\_recap/recap/agents/ai\_agent.py                |      119 |       74 |     38% |56-100, 105-115, 167-217, 225-236 |
| src/news\_recap/recap/agents/echo.py                     |       20 |       20 |      0% |     19-53 |
| src/news\_recap/recap/agents/routing.py                  |       95 |       17 |     82% |41, 53-61, 90, 116, 121, 145, 177, 179, 182, 184, 186, 188, 190 |
| src/news\_recap/recap/agents/subprocess.py               |      109 |       39 |     64% |22-23, 57, 68, 80-81, 88, 105-106, 125, 127, 131, 134, 145-146, 148, 172-205, 209-220 |
| src/news\_recap/recap/contracts.py                       |       67 |       32 |     52% |49-50, 56-59, 65, 71-81, 87, 93-125, 131 |
| src/news\_recap/recap/flow.py                            |       88 |       59 |     33% |48-62, 66-69, 76-77, 91-157 |
| src/news\_recap/recap/launcher.py                        |       92 |       22 |     76% |66, 78, 81-83, 86-92, 96, 111-121, 182-208 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       51 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      123 |       13 |     89% |85, 174-180, 184-186, 208, 219, 265, 274-275, 278, 281 |
| src/news\_recap/recap/models.py                          |       52 |        8 |     85% |24-29, 32, 41 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      149 |       27 |     82% |78-81, 94-97, 111-131, 142-148, 171, 177-178, 192, 241, 252, 287 |
| src/news\_recap/recap/storage/schemas.py                 |        1 |        1 |      0% |         7 |
| src/news\_recap/recap/storage/workdir.py                 |       30 |       19 |     37% | 30, 40-71 |
| src/news\_recap/recap/tasks/base.py                      |       52 |        6 |     88% |89-91, 100, 104, 107 |
| src/news\_recap/recap/tasks/classify.py                  |      152 |       19 |     88% |133, 139, 219-228, 238, 245-246, 251, 291-293 |
| src/news\_recap/recap/tasks/enrich.py                    |      165 |       16 |     90% |130-131, 168, 197-198, 261-266, 286-290, 301, 314-315, 356 |
| src/news\_recap/recap/tasks/group\_sections.py           |      120 |       23 |     81% |75, 147, 199-245 |
| src/news\_recap/recap/tasks/load\_resources.py           |       57 |        6 |     89% |44, 86-87, 93-95 |
| src/news\_recap/recap/tasks/map\_blocks.py               |      144 |        8 |     94% |151, 217, 231-233, 249-250, 293 |
| src/news\_recap/recap/tasks/parallel.py                  |       51 |       10 |     80% |80-87, 107, 128 |
| src/news\_recap/recap/tasks/prompts.py                   |        8 |        0 |    100% |           |
| src/news\_recap/recap/tasks/reduce\_blocks.py            |      237 |       74 |     69% |63, 174, 216-233, 330-350, 366-390, 398-474, 483-496 |
| src/news\_recap/recap/tasks/split\_blocks.py             |       96 |        1 |     99% |       123 |
| src/news\_recap/recap/tasks/summarize.py                 |       50 |       12 |     76% |    79-108 |
| src/news\_recap/storage/io.py                            |       50 |        5 |     90% | 35-38, 61 |
| **TOTAL**                                                | **4220** |  **798** | **81%** |           |


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