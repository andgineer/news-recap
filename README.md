# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      117 |       15 |     87% |152, 159, 175, 177, 187-188, 192, 206, 208, 227-232 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        7 |     87% |41, 45-46, 75, 98-99, 105 |
| src/news\_recap/ingestion/controllers.py                 |      120 |       61 |     49% |69-117, 120-170, 173-213, 216-251, 261-264, 276, 293, 300-302 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       29 |     59% |27-30, 40, 52, 55-72, 83-86, 89-91, 111, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      148 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |       20 |     49% |36-50, 56-82, 93 |
| src/news\_recap/ingestion/repository.py                  |      396 |      321 |     19% |89-91, 99-153, 160-172, 175-177, 186-208, 217-247, 255-267, 292-302, 312-402, 415-433, 436-484, 487-504, 507-519, 533-545, 553-563, 573-595, 603-613, 627-651, 660-680, 688-699, 702-712, 726-743, 755-787, 797-840, 843-852, 859-879, 895-934, 944-963, 977, 990, 994, 998-999, 1006-1008, 1016, 1038, 1042-1043, 1047-1049, 1053-1055, 1059-1061, 1065 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       51 |        6 |     88% |35-41, 97-99, 109 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |       49 |     25% |38-41, 44-57, 72-128, 131-132 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        5 |     64% |22-23, 26-33 |
| src/news\_recap/ingestion/sources/base.py                |       31 |        4 |     87% |19, 46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      413 |      113 |     73% |45, 56, 70, 81, 91, 100, 197, 314, 328, 341, 365-370, 391, 393, 404-444, 454-461, 470-493, 504-505, 511-512, 520-533, 584-622, 626-640, 658-663, 667-670, 710, 715, 719, 738-739, 749, 757 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       15 |        9 |     40% |12, 18-21, 27-30 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      137 |        0 |    100% |           |
| src/news\_recap/main.py                                  |       46 |        5 |     89% |81, 147, 202, 217-218 |
| **TOTAL**                                                | **1892** |  **682** | **64%** |           |


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