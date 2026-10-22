# 响应样例

以下是用 `ledger/seed.py --samples` 导入的**虚构样例数据**在本机实例上的真实接口输出（只读 token），
人名、期刊、稿号全部是编的；结构和字段与当前版本一致。时间戳是生成样例当天的服务器时间。

生成方法：`python3 seed.py --api-tokens --samples` 后启动服务，再

```bash
curl -s -A sample -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8611/api/v1/papers/P01
```

## `GET /papers/P01`

```json
{
  "code": "P01",
  "title": "A Survey of Example Methods for Image Segmentation",
  "title_cn": "图像分割方法综述",
  "status": "投稿中",
  "authors": [
    "San Zhang",
    "Alice Example",
    "Bob Example"
  ],
  "corresponding": "Alice Example",
  "lead_author": "张三",
  "follow_mode": "self",
  "follow_mode_label": "本人自查",
  "current_note": "外审中，等第二位审稿人意见",
  "my_author_position": "第一作者",
  "i_am_corresponding": false,
  "category": "主序列",
  "notes": "",
  "updated_at": "2026-10-22 15:37:33",
  "submission_count": 2,
  "current_journal": "Example Letters",
  "current_submission": {
    "id": 2,
    "seq": 2,
    "journal": "Example Letters",
    "submit_date": "2026-03-20",
    "manuscript_id": "EXL-2026-0042",
    "status": "投稿中",
    "outcome": "",
    "display_status": "投稿中",
    "is_current": true,
    "result_date": null,
    "site_url": "https://mc.manuscriptcentral.com/example",
    "notes": null,
    "credentials_present": {
      "sys_account": false,
      "sys_password": false,
      "sys_cookie": false
    }
  },
  "days_since_current_submit": 216,
  "submissions": [
    {
      "id": 2,
      "seq": 2,
      "journal": "Example Letters",
      "submit_date": "2026-03-20",
      "manuscript_id": "EXL-2026-0042",
      "status": "投稿中",
      "outcome": "",
      "display_status": "投稿中",
      "is_current": true,
      "result_date": null,
      "site_url": "https://mc.manuscriptcentral.com/example",
      "notes": null,
      "credentials_present": {
        "sys_account": false,
        "sys_password": false,
        "sys_cookie": false
      }
    },
    {
      "id": 1,
      "seq": 1,
      "journal": "Journal of Example Studies",
      "submit_date": "2026-01-15",
      "manuscript_id": "JES-2026-0001",
      "status": "已转投",
      "outcome": "被拒",
      "display_status": "已转投（被拒）",
      "is_current": false,
      "result_date": "2026-03-02",
      "site_url": "https://www.editorialmanager.com/example/",
      "notes": "编辑认为范围不符",
      "credentials_present": {
        "sys_account": false,
        "sys_password": false,
        "sys_cookie": false
      }
    }
  ],
  "review_stage": "未标注",
  "last_progress_date": null,
  "last_checked_date": null,
  "days_without_progress": 216,
  "days_since_last_check": null,
  "revision_due_date": null,
  "revision_days_remaining": null,
  "progress_date_basis": "submit_date",
  "files": [],
  "events": [],
  "server_time": "2026-10-22 15:38:08",
  "timezone": "Asia/Shanghai"
}
```

## `GET /stats`

```json
{
  "total": 4,
  "by_status": {
    "已录用": 1,
    "投稿中": 2,
    "撰写中": 1
  },
  "by_author_position": {
    "第一作者": 3,
    "第二作者": 1
  },
  "corresponding_count": 1,
  "by_category": {
    "主序列": 3,
    "其他论文（不计入主序列）": 1,
    "合作方论文": 0
  },
  "main_series": {
    "total": 3,
    "by_status": {
      "投稿中": 2,
      "撰写中": 1
    },
    "by_author_position": {
      "第一作者": 3
    },
    "corresponding_count": 1
  },
  "generated_at": "2026-10-22 15:38:08",
  "timezone": "Asia/Shanghai"
}
```

## `GET /papers?status=%E6%8A%95%E7%A8%BF%E4%B8%AD` 列表（截取一条）

```json
{
  "count": 2,
  "server_time": "2026-10-22 15:38:08",
  "timezone": "Asia/Shanghai",
  "papers": [
    {
      "code": "P01",
      "title": "A Survey of Example Methods for Image Segmentation",
      "title_cn": "图像分割方法综述",
      "status": "投稿中",
      "authors": [
        "San Zhang",
        "Alice Example",
        "Bob Example"
      ],
      "corresponding": "Alice Example",
      "lead_author": "张三",
      "follow_mode": "self",
      "follow_mode_label": "本人自查",
      "current_note": "外审中，等第二位审稿人意见",
      "my_author_position": "第一作者",
      "i_am_corresponding": false,
      "category": "主序列",
      "notes": "",
      "updated_at": "2026-10-22 15:37:33",
      "submission_count": 2,
      "current_journal": "Example Letters",
      "current_submission": {
        "id": 2,
        "seq": 2,
        "journal": "Example Letters",
        "submit_date": "2026-03-20",
        "manuscript_id": "EXL-2026-0042",
        "status": "投稿中",
        "outcome": "",
        "display_status": "投稿中",
        "is_current": true,
        "result_date": null,
        "site_url": "https://mc.manuscriptcentral.com/example",
        "notes": null,
        "credentials_present": {
          "sys_account": false,
          "sys_password": false,
          "sys_cookie": false
        }
      },
      "days_since_current_submit": 216,
      "submissions": [
        {
          "id": 2,
          "seq": 2,
          "journal": "Example Letters",
          "submit_date": "2026-03-20",
          "manuscript_id": "EXL-2026-0042",
          "status": "投稿中",
          "outcome": "",
          "display_status": "投稿中",
          "is_current": true,
          "result_date": null,
          "site_url": "https://mc.manuscriptcentral.com/example",
          "notes": null,
          "credentials_present": {
            "sys_account": false,
            "sys_password": false,
            "sys_cookie": false
          }
        },
        {
          "id": 1,
          "seq": 1,
          "journal": "Journal of Example Studies",
          "submit_date": "2026-01-15",
          "manuscript_id": "JES-2026-0001",
          "status": "已转投",
          "outcome": "被拒",
          "display_status": "已转投（被拒）",
          "is_current": false,
          "result_date": "2026-03-02",
          "site_url": "https://www.editorialmanager.com/example/",
          "notes": "编辑认为范围不符",
          "credentials_present": {
            "sys_account": false,
            "sys_password": false,
            "sys_cookie": false
          }
        }
      ],
      "review_stage": "未标注",
      "last_progress_date": null,
      "last_checked_date": null,
      "days_without_progress": 216,
      "days_since_last_check": null,
      "revision_due_date": null,
      "revision_days_remaining": null,
      "progress_date_basis": "submit_date"
    },
    "…其余省略…"
  ]
}
```
