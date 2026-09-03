#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static base data used by stocktrend."""
from __future__ import annotations

import json


HK_BASE_DATA = json.loads(r'''
{
  "meta": {
    "title": "港股二级业务类别个股走势分析",
    "tag": "收盘快照 · 运行时生成",
    "subtitle": "恒生指数公司官方分类（2025版）· 12个一级行业 · 31个二级业务类别 · 40只代表股（覆盖周期/消费/科技/金融四大板块）· 点击卡片查看个股深度分析",
    "date": "行情、估值、财务、分红、南向持股等事实字段由运行时实时获取；港股惯例：涨红跌绿",
    "databadge": "⚠️ 数据口径：本文件仅保留静态模板配置，如行业分类、基础股票名单与风险提示。行情、估值、财务、分红、南向持股等动态字段不在此固化。",
    "disclaimer": "⚠️ 免责声明：以上内容由 AI 基于公开数据与静态模板整理生成，仅供参考，不构成任何投资建议或个股推荐。行业分类、组合分组与风险提示为静态模板配置；价格、估值、财务、分红、南向持股等事实字段以运行时实时数据为准。",
    "footer": "港股二级业务类别个股走势分析 · 静态模板配置（行业分类 / 风险提示）",
    "roster_title": "ROE 分层观察名单（港股）",
    "roster_note": "ROE 为运行时可获取的最新公开口径；若缺失则不强行补值。",
    "combo_section_title": "三种组合 · 稳健/成长各 5 只 · 进取 7 只",
    "combo_note": "单只标的建议不超过组合的 15%-20%，并严格分散行业与风格。",
    "snap_iso": "",
    "modal_databadge": "⚠️ 数据口径：本文件不再固化价格、估值、财务、分红、南向持股等动态字段；页面展示时优先使用运行时实时公开数据。"
  },
  "sectors": [
    {
      "key": "cycle",
      "title": "大周期板块（3个一级行业 · 8个二级类别 · 8只代表股）",
      "label": "周期板块",
      "color": "#ff8c42"
    },
    {
      "key": "consumer",
      "title": "大消费板块（3个一级行业 · 12个二级类别 · 18只代表股）",
      "label": "消费板块",
      "color": "#f0c040"
    },
    {
      "key": "tech",
      "title": "大科技板块（1个一级行业 · 3个二级类别 · 6只代表股）",
      "label": "科技板块",
      "color": "#3fb950"
    },
    {
      "key": "finance",
      "title": "大金融/公用/综合板块（5个一级行业 · 8个二级类别 · 8只代表股）",
      "label": "金融/公用板块",
      "color": "#58a6ff"
    }
  ],
  "stocks": [
    {
      "code": "00883",
      "en": "CNOOC",
      "zh": "中国海洋石油",
      "sector": "cycle",
      "l1": "能源业",
      "l2_code": "0010",
      "l2": "石油及天然气",
      "border": "red",
      "risks": [
        "国际油价大幅回落（如跌破 60 美元/桶）",
        "上游资本开支加大、储量替代率下行",
        "海外资产地缘政治与制裁风险"
      ]
    },
    {
      "code": "01088",
      "en": "China Shenhua",
      "zh": "中国神华",
      "sector": "cycle",
      "l1": "能源业",
      "l2_code": "0020",
      "l2": "煤炭",
      "border": "brown",
      "risks": [
        "煤价中枢中长期下行（绿电替代加速）",
        "长协政策调整影响盈利稳定性",
        "当前 52w位 75%，进一步上行空间有限"
      ]
    },
    {
      "code": "01818",
      "en": "Zhaojin Mining",
      "zh": "招金矿业",
      "sector": "cycle",
      "l1": "原材料业",
      "l2_code": "0510",
      "l2": "黄金及贵金属",
      "border": "yellow",
      "risks": [
        "国际金价大幅回落（美元走强、避险情绪降温）",
        "矿山安全事故/资源国政策变动",
        "短期 20日已涨 22%，技术性回调压力"
      ]
    },
    {
      "code": "02899",
      "en": "Zijin Mining",
      "zh": "紫金矿业",
      "sector": "cycle",
      "l1": "原材料业",
      "l2_code": "0520",
      "l2": "一般金属及矿石",
      "border": "orange",
      "risks": [
        "金/铜价大幅回落",
        "海外矿山运营与社区冲突风险",
        "汇率与资源国政策变动"
      ]
    },
    {
      "code": "02689",
      "en": "Nine Dragons Paper",
      "zh": "玖龙纸业",
      "sector": "cycle",
      "l1": "原材料业",
      "l2_code": "0530",
      "l2": "原材料（纸品）",
      "border": "gray",
      "risks": [
        "纸品价格下行、原辅料成本上行",
        "单日 -16% 异动可能反映业绩或行业重大利空",
        "出口需求疲软、内需恢复缓慢"
      ]
    },
    {
      "code": "01766",
      "en": "CRRC",
      "zh": "中国中车",
      "sector": "cycle",
      "l1": "工业",
      "l2_code": "1010",
      "l2": "工业工程",
      "border": "blue",
      "risks": [
        "国内轨交投资增速放缓",
        "海外订单交付与汇率风险",
        "动车组招标节奏不及预期"
      ]
    },
    {
      "code": "01919",
      "en": "COSCO Shipping",
      "zh": "中远海控",
      "sector": "cycle",
      "l1": "工业",
      "l2_code": "1020",
      "l2": "工用运输（航运）",
      "border": "purple",
      "risks": [
        "红海通航恢复、运价大幅回落",
        "全球贸易需求转弱",
        "新船交付带来的供给压力"
      ]
    },
    {
      "code": "00636",
      "en": "KLN",
      "zh": "嘉里物流",
      "sector": "cycle",
      "l1": "工业",
      "l2_code": "1030",
      "l2": "工用支援（物流）",
      "border": "green",
      "risks": [
        "全球货量需求下行、运价回落",
        "整合协同效应不及预期",
        "小市值流动性偏低"
      ]
    },
    {
      "code": "01211",
      "en": "BYD",
      "zh": "比亚迪股份",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2310",
      "l2": "汽车（新能源车）",
      "border": "blue",
      "risks": [
        "国内新能源车价格战挤压毛利",
        "海外关税与贸易壁垒升级",
        "电池技术路线迭代风险"
      ]
    },
    {
      "code": "02015",
      "en": "Li Auto",
      "zh": "理想汽车-W",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2310",
      "l2": "汽车（增程/纯电）",
      "border": "green",
      "risks": [
        "新能源车价格战挤压毛利",
        "纯电车型（MEGA 等）交付不及预期",
        "增程路线受插混竞争冲击"
      ]
    },
    {
      "code": "09868",
      "en": "XPeng",
      "zh": "小鹏集团-W",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2310",
      "l2": "汽车（智能电动）",
      "border": "purple",
      "risks": [
        "亏损持续、现金消耗",
        "Robotaxi 商业化不及预期",
        "价格战与销量波动"
      ]
    },
    {
      "code": "00669",
      "en": "Techtronic Industries",
      "zh": "创科实业",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2320",
      "l2": "家庭电器及用品（电动工具）",
      "border": "orange",
      "risks": [
        "美/欧地产链需求转弱（电动工具主市场）",
        "渠道库存与价格战风险",
        "估值溢价回归风险（52w位 88%）"
      ]
    },
    {
      "code": "02020",
      "en": "ANTA Sports",
      "zh": "安踏体育",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2330",
      "l2": "纺织及服饰（运动鞋服）",
      "border": "red",
      "risks": [
        "国内消费疲软、库存压力",
        "FILA / Amer 多品牌整合执行",
        "海外扩张不及预期"
      ]
    },
    {
      "code": "09961",
      "en": "Trip.com Group",
      "zh": "携程集团-S",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2340",
      "l2": "旅游及消闲设施",
      "border": "purple",
      "risks": [
        "出境游恢复不及预期（地缘/签证/消费疲软）",
        "国内酒店间夜量增速放缓",
        "海外业务受宏观影响"
      ]
    },
    {
      "code": "09888",
      "en": "Baidu",
      "zh": "百度集团-SW",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2350",
      "l2": "媒体及娱乐（搜索/AI）",
      "border": "green",
      "risks": [
        "AI 投入高企拖累盈利",
        "广告收入增速放缓",
        "搜索份额受 AI 应用分流"
      ]
    },
    {
      "code": "01024",
      "en": "Kuaishou",
      "zh": "快手-W",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2350",
      "l2": "媒体及娱乐（短视频/AI）",
      "border": "blue",
      "risks": [
        "Q2 净利 -30%，盈利下滑趋势未止",
        "直播/电商变现增速放缓",
        "单日 -11% 放量异动反映筹码松动"
      ]
    },
    {
      "code": "09626",
      "en": "Bilibili",
      "zh": "哔哩哔哩-W",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2350",
      "l2": "媒体及娱乐（视频/游戏）",
      "border": "orange",
      "risks": [
        "游戏收入波动大",
        "广告与会员增长放缓",
        "Z世代消费力受宏观影响"
      ]
    },
    {
      "code": "06989",
      "en": "Excellence Commercial",
      "zh": "卓越商企服务",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2360",
      "l2": "支援服务（商业管理）",
      "border": "brown",
      "risks": [
        "商业地产空置率与物管费收缴率",
        "关联地产（卓越集团）信用风险",
        "小盘股流动性极低，不适合大资金"
      ]
    },
    {
      "code": "00881",
      "en": "Zhongsheng Group",
      "zh": "中升控股",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2370",
      "l2": "专业零售（汽车经销）",
      "border": "gray",
      "risks": [
        "国内新车价格战挤压经销毛利",
        "豪华车市场恢复不及预期",
        "盈利转正拐点未明"
      ]
    },
    {
      "code": "09988",
      "en": "Alibaba",
      "zh": "阿里巴巴-W",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2370",
      "l2": "专业零售（线上零售商）",
      "border": "orange",
      "risks": [
        "被列入美国\"中国军事企业清单\"带来制裁与情绪扰动",
        "电商竞争（拼多多/抖音）",
        "云业务增速不及预期"
      ]
    },
    {
      "code": "03690",
      "en": "Meituan",
      "zh": "美团-W",
      "sector": "consumer",
      "l1": "非必需性消费",
      "l2_code": "2370",
      "l2": "专业零售（本地生活/线上零售）",
      "border": "brown",
      "risks": [
        "外卖/到店价格战（抖音、阿里即时零售）",
        "消费疲软拖累客单价",
        "AI 投入加大压缩利润率"
      ]
    },
    {
      "code": "02319",
      "en": "Mengniu Dairy",
      "zh": "蒙牛乳业",
      "sector": "consumer",
      "l1": "必需性消费",
      "l2_code": "2510",
      "l2": "食物饮品（乳业）",
      "border": "yellow",
      "risks": [
        "原奶成本与终端价格博弈",
        "消费复苏节奏不及预期",
        "行业竞争与营销费用压力"
      ]
    },
    {
      "code": "01610",
      "en": "COFCO Joycome",
      "zh": "中粮家佳康",
      "sector": "consumer",
      "l1": "必需性消费",
      "l2_code": "2520",
      "l2": "农业产品（生猪养殖）",
      "border": "green",
      "risks": [
        "猪价持续低迷、深度亏损延长",
        "饲料成本与防疫压力",
        "周期反转节奏不确定"
      ]
    },
    {
      "code": "09618",
      "en": "JD.com",
      "zh": "京东集团-SW",
      "sector": "consumer",
      "l1": "必需性消费",
      "l2_code": "2530",
      "l2": "消费者主要零售商（电商）",
      "border": "red",
      "risks": [
        "国内电商份额竞争（拼多多/抖音）",
        "京东物流盈利改善节奏",
        "消费疲软影响 GMV 增速"
      ]
    },
    {
      "code": "02269",
      "en": "WuXi Biologics",
      "zh": "药明生物",
      "sector": "consumer",
      "l1": "医疗保健业",
      "l2_code": "2810",
      "l2": "药品及生物科技（CDMO）",
      "border": "purple",
      "risks": [
        "全球生物药投融资冷暖（订单驱动）",
        "海外业务地缘政治风险",
        "短期急涨后技术性回调压力"
      ]
    },
    {
      "code": "01099",
      "en": "Sinopharm",
      "zh": "国药控股",
      "sector": "consumer",
      "l1": "医疗保健业",
      "l2_code": "2820",
      "l2": "其他医疗保健（医药流通）",
      "border": "blue",
      "risks": [
        "集采降价对流通环节压力",
        "应收账款与账期风险",
        "医院终端需求疲软"
      ]
    },
    {
      "code": "00992",
      "en": "Lenovo Group",
      "zh": "联想集团",
      "sector": "tech",
      "l1": "资讯科技业",
      "l2_code": "7010",
      "l2": "资讯科技器材（PC+服务器）",
      "border": "gray",
      "risks": [
        "AI 主题炒作退潮（近 5日 -15%）",
        "PC 市场需求持续疲软",
        "高位估值回归风险（PE 59）"
      ]
    },
    {
      "code": "01810",
      "en": "Xiaomi",
      "zh": "小米集团-W",
      "sector": "tech",
      "l1": "资讯科技业",
      "l2_code": "7010",
      "l2": "资讯科技器材（消费电子+智能汽车）",
      "border": "blue",
      "risks": [
        "新能源车价格战压缩小米汽车毛利",
        "智能手机份额与高端化进展不及预期",
        "海外地缘与关税风险"
      ]
    },
    {
      "code": "00268",
      "en": "Kingdee International",
      "zh": "金蝶国际",
      "sector": "tech",
      "l1": "资讯科技业",
      "l2_code": "7020",
      "l2": "软件服务（云ERP/SaaS）",
      "border": "purple",
      "risks": [
        "云收入增速不及预期",
        "传统ERP业务萎缩",
        "高 PE 估值回归"
      ]
    },
    {
      "code": "00700",
      "en": "Tencent",
      "zh": "腾讯控股",
      "sector": "tech",
      "l1": "资讯科技业",
      "l2_code": "7020",
      "l2": "软件服务（互联网平台）",
      "border": "red",
      "risks": [
        "游戏版号与爆款节奏",
        "AI 竞争（字节等）冲击广告/内容份额",
        "宏观与地缘影响外资情绪"
      ]
    },
    {
      "code": "09999",
      "en": "NetEase",
      "zh": "网易",
      "sector": "tech",
      "l1": "资讯科技业",
      "l2_code": "7020",
      "l2": "软件服务（游戏/互联网）",
      "border": "green",
      "risks": [
        "国内游戏版号节奏",
        "暴雪/海外游戏合作变化",
        "新游戏流水不及预期"
      ]
    },
    {
      "code": "00981",
      "en": "SMIC",
      "zh": "中芯国际",
      "sector": "tech",
      "l1": "资讯科技业",
      "l2_code": "7030",
      "l2": "半导体（晶圆代工）",
      "border": "yellow",
      "risks": [
        "半导体周期下行",
        "先进制程突破节奏",
        "海外设备/技术管制升级"
      ]
    },
    {
      "code": "00941",
      "en": "China Mobile",
      "zh": "中国移动",
      "sector": "finance",
      "l1": "电讯业",
      "l2_code": "3500",
      "l2": "电讯",
      "border": "orange",
      "risks": [
        "资本开支压力（算力/5G）压制自由现金流",
        "携号转网与竞争",
        "利率下行对高息重定价"
      ]
    },
    {
      "code": "00836",
      "en": "China Resources Power",
      "zh": "华润电力",
      "sector": "finance",
      "l1": "公用事业",
      "l2_code": "4000",
      "l2": "公用事业（电力）",
      "border": "yellow",
      "risks": [
        "煤价波动影响火电盈利",
        "新能源消纳与电价",
        "来水/风光不及预期"
      ]
    },
    {
      "code": "00005",
      "en": "HSBC Holdings",
      "zh": "汇丰控股",
      "sector": "finance",
      "l1": "金融业",
      "l2_code": "5010",
      "l2": "银行",
      "border": "red",
      "risks": [
        "英国/港地产敞口",
        "净息差随降息收窄",
        "地缘政治与合规成本"
      ]
    },
    {
      "code": "01299",
      "en": "AIA Group",
      "zh": "友邦保险",
      "sector": "finance",
      "l1": "金融业",
      "l2_code": "5020",
      "l2": "保险",
      "border": "blue",
      "risks": [
        "新业务价值（NBV）增速",
        "利率下行影响投资收益",
        "内地访客业务恢复"
      ]
    },
    {
      "code": "00388",
      "en": "HKEX",
      "zh": "香港交易所",
      "sector": "finance",
      "l1": "金融业",
      "l2_code": "5030",
      "l2": "其他金融（交易所）",
      "border": "green",
      "risks": [
        "港股交投活跃度下降",
        "新股 IPO 节奏放缓",
        "高估值回归"
      ]
    },
    {
      "code": "01109",
      "en": "China Resources Land",
      "zh": "华润置地",
      "sector": "finance",
      "l1": "地产建筑业",
      "l2_code": "6010",
      "l2": "地产",
      "border": "brown",
      "risks": [
        "销售回款与去化",
        "房价下行计提",
        "商业地产空置率"
      ]
    },
    {
      "code": "03311",
      "en": "China State Construction Int'l",
      "zh": "中国建筑国际",
      "sector": "finance",
      "l1": "地产建筑业",
      "l2_code": "6020",
      "l2": "建筑",
      "border": "orange",
      "risks": [
        "订单回款与项目执行",
        "海外项目地缘风险",
        "建筑行业景气"
      ]
    },
    {
      "code": "00001",
      "en": "CK Hutchison",
      "zh": "长和",
      "sector": "finance",
      "l1": "综合企业",
      "l2_code": "8000",
      "l2": "综合企业",
      "border": "blue",
      "risks": [
        "全球电信/零售/基建受宏观利率影响",
        "港口业务受全球贸易量波动",
        "GBP/EUR 汇率敞口"
      ]
    }
  ]
}
''')
