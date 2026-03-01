# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      222 |       50 |     77% |220, 224, 226, 232, 238, 241, 245, 260, 262, 264, 266, 270, 272, 300, 307, 323, 325, 335-336, 340, 407-424, 433, 435, 451-459, 465, 475, 482, 489 |
| src/news\_recap/http/fetcher.py                          |       42 |        4 |     90% |47, 92, 95, 98 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        7 |     76% |47-49, 60-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       94 |       15 |     84% |116-120, 140, 144, 158, 160-165, 190, 198 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        1 |     98% |        75 |
| src/news\_recap/ingestion/controllers.py                 |       66 |        3 |     95% |110, 129, 176 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      149 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       35 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      255 |       17 |     93% |92, 134, 205, 219, 221, 229-234, 247, 316, 394, 542-545 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/main.py                                  |       50 |        1 |     98% |       191 |
| src/news\_recap/recap/agents/ai\_agent.py                |      148 |       99 |     33% |47-98, 102-105, 133-136, 141-147, 152-167, 221-273, 281-292 |
| src/news\_recap/recap/agents/echo.py                     |       20 |       20 |      0% |     19-53 |
| src/news\_recap/recap/agents/routing.py                  |       96 |       17 |     82% |42, 54-62, 91, 117, 122, 146, 178, 180, 183, 185, 187, 189, 191 |
| src/news\_recap/recap/agents/subprocess.py               |      162 |       83 |     49% |27-28, 62, 73, 85-86, 93, 110-111, 130, 132, 136, 139, 150-151, 153, 190-273, 277-280, 285-301, 305-316 |
| src/news\_recap/recap/contracts.py                       |       67 |       32 |     52% |49-50, 56-59, 65, 71-81, 87, 93-125, 131 |
| src/news\_recap/recap/dedup/calibration.py               |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/recap/dedup/cluster.py                   |       51 |        2 |     96% |    62, 66 |
| src/news\_recap/recap/dedup/embedder.py                  |       71 |       29 |     59% |27-30, 40, 52, 55-72, 83-86, 89-91, 110, 117 |
| src/news\_recap/recap/flow.py                            |       89 |       62 |     30% |46-60, 64-67, 80-152 |
| src/news\_recap/recap/launcher.py                        |       89 |       22 |     75% |67, 79, 82-84, 87-93, 97, 114-126, 183-211 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       51 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      123 |       13 |     89% |85, 174-180, 184-186, 208, 219, 265, 274-275, 278, 281 |
| src/news\_recap/recap/models.py                          |       53 |        8 |     85% |24-29, 32, 41 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      145 |       15 |     90% |61, 94-100, 123, 129-130, 144, 196, 207, 242 |
| src/news\_recap/recap/storage/schemas.py                 |        1 |        1 |      0% |         7 |
| src/news\_recap/recap/storage/workdir.py                 |       53 |       32 |     40% |35, 45-76, 84-87, 100-103, 117-137 |
| src/news\_recap/recap/tasks/base.py                      |       65 |       11 |     83% |61-72, 124-126, 135, 139, 142 |
| src/news\_recap/recap/tasks/classify.py                  |      149 |       19 |     87% |132, 138, 213-222, 230, 237-238, 243, 283-285 |
| src/news\_recap/recap/tasks/deduplicate.py               |      184 |       87 |     53% |47-51, 55-59, 152-179, 184-205, 215-252, 263-278, 291-292, 302-314, 324-328 |
| src/news\_recap/recap/tasks/enrich.py                    |      187 |       15 |     92% |135, 201, 228-229, 292-297, 317-321, 331, 344-345, 386 |
| src/news\_recap/recap/tasks/group\_sections.py           |      110 |       20 |     82% |68, 140, 192-224 |
| src/news\_recap/recap/tasks/load\_resources.py           |       55 |        6 |     89% |42, 83-84, 90-92 |
| src/news\_recap/recap/tasks/map\_blocks.py               |      140 |        8 |     94% |150, 210, 222-224, 240-241, 284 |
| src/news\_recap/recap/tasks/parallel.py                  |       66 |       15 |     77% |77, 91-98, 120, 126-129, 147 |
| src/news\_recap/recap/tasks/prompts.py                   |        9 |        0 |    100% |           |
| src/news\_recap/recap/tasks/reduce\_blocks.py            |      226 |       69 |     69% |65, 168, 210-213, 310-328, 344-356, 364-440, 449-462 |
| src/news\_recap/recap/tasks/split\_blocks.py             |       92 |        1 |     99% |       114 |
| src/news\_recap/recap/tasks/summarize.py                 |       40 |        9 |     78% |     72-86 |
| src/news\_recap/storage/io.py                            |       50 |        5 |     90% | 35-38, 61 |
| **TOTAL**                                                | **4211** |  **953** | **77%** |           |


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