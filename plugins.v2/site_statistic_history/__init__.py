import json
import re
import warnings
from datetime import datetime, timedelta
from multiprocessing.dummy import Pool as ThreadPool
from threading import Lock
from typing import Optional, Any, List, Dict, Tuple

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from ruamel.yaml import CommentedMap

from app import schemas
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.db.models import PluginData
from app.db.site_oper import SiteOper
from app.helper.browser import PlaywrightHelper
from app.helper.module import ModuleHelper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.sitestatistic.siteuserinfo import ISiteUserInfo
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from app.utils.object import ObjectUtils
from app.utils.string import StringUtils
from app.utils.timer import TimerUtils

class SiteStatisticHistory(_PluginBase):
    # 插件名称
    plugin_name = "站点历史数据"
    # 插件描述
    plugin_desc = "历史数据统计。"
    # 插件图标
    plugin_icon = "refresh.png"
    # 插件版本
    plugin_version = "0.2"
    # 插件作者
    plugin_author = "123"
    # 作者主页
    author_url = "https://github.com/798love"
    # 插件配置项ID前缀
    plugin_config_prefix = "site_statistic_history_"
    # 加载顺序
    plugin_order = 98
    # 可使用的用户级别
    auth_level = 1

    _enabled = False


    def init_plugin(self, config: dict = None):
        logger.error("tst")
        pass

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件1",
                                            'direction':'vertical',
                                        },
                                    }
                                ],
                            },
                            
                        ],
                    },
                    
                ],
            }
        ], {
            "enabled": False,

        }
            
    def __get_data(self) -> Tuple[str, dict, dict]:
        """
        获取今天的日期、今天的站点数据、昨天的站点数据
        """
        # 最近一天的签到数据
        stattistic_data: Dict[str, Dict[str, Any]] = {}
        # 昨天数据
        yesterday_sites_data: Dict[str, Dict[str, Any]] = {}
        # 获取最近所有数据
        data_list: List[PluginData] = self.get_data(plugin_id='SiteStatistic')
        # logger.info(data_list)
        if not data_list:
            return "", {}, {}
        # 取key符合日期格式的数据
        data_list = [data for data in data_list if re.match(r"\d{4}-\d{2}-\d{2}", data.key)]
        # logger.info(data_list)
        # 按日期倒序排序
        data_list.sort(key=lambda x: x.key, reverse=True)
        # 今天的日期
        today = data_list[0].key
        logger.info(today)
        # 数据按时间降序排序
        datas = [json.loads(data.value) for data in data_list if ObjectUtils.is_obj(data.value)]
        if len(data_list) > 0:
            stattistic_data = datas[0]
        if len(data_list) > 1:
            yesterday_sites_data = datas[1]
        # logger.info(datas)
        # 数据按时间降序排序
        stattistic_data = dict(sorted(stattistic_data.items(),
                                      key=lambda item: item[1].get('upload') or 0,
                                      reverse=True))
        return today, stattistic_data, yesterday_sites_data

    @staticmethod
    def __gb(value: int) -> float:
        """
        转换为GB，保留1位小数
        """
        if not value:
            return 0
        return round(float(value) / 1024 / 1024 / 1024, 1)

    @staticmethod
    def __sub_dict(d1: dict, d2: dict) -> dict:
        """
        计算两个字典相同Key值的差值（如果值为数字），返回新字典
        """
        if not d1:
            return {}
        if not d2:
            return d1
        d = {k: int(d1.get(k)) - int(d2.get(k)) for k in d1
                if k in d2 and str(d1.get(k)).isdigit() and str(d2.get(k)).isdigit()}
        # 把小于0的数据变成0
        for k, v in d.items():
            if str(v).isdigit() and int(v) < 0:
                d[k] = 0
        return d


    def __get_7_inc11(self):
        data_list: List[PluginData] = self.get_data(plugin_id='SiteStatistic')
        if not data_list:
            return {}
        # 取key符合日期格式的数据
        data_list = [data for data in data_list if re.match(r"\d{4}-\d{2}-\d{2}", data.key)]
        # logger.info(data_list)
        # 按日期倒序排序
        # data_list.sort(key=lambda x: x.key, reverse=True)
        data_list.sort(key=lambda x: x.key, reverse=False)
        # 今天的日期
        today = data_list[-1].key
        logger.info(today)
        # 数据按时间降序排序
        datas = [json.loads(data.value) for data in data_list if ObjectUtils.is_obj(data.value)]
        # logger.info(datas)
        dates = [dat.key for dat in data_list][1:]
        logger.info(dates)
        incs=[]
        daily_incs_all=[]
        daily_dl_all=[]
        for i in range(len(datas)-1):
            inc_data = {}
            for site, data in datas[i+1].items():
                inc = self.__sub_dict(data, datas[i].get(site))
                if inc:
                    inc_data[site] = inc
            incs.append(inc_data)

            uploads = {k: v for k, v in inc_data.items() if v.get("upload")}
            upload_datas = [self.__gb(data.get("upload")) for data in uploads.values()]
            today_upload = round(sum(upload_datas), 2)
            daily_incs_all.append(today_upload)

            downloads = {k: v for k, v in inc_data.items() if v.get("download")}
            download_datas = [self.__gb(data.get("download")) for data in downloads.values()]
            today_download = round(sum(download_datas), 2)
            daily_dl_all.append(today_download)

        logger.info(daily_incs_all)
        if len(daily_incs_all)>15:
            return dates[-15:],daily_incs_all[-15:],daily_dl_all[-15:]
        else:
            return dates,daily_incs_all,daily_dl_all

        return dates,daily_incs_all,daily_dl_all

    def __get_sum(self):
        data_list: List[PluginData] = self.get_data(plugin_id='SiteStatistic')
        if not data_list:
            return {}
        data_list = [data for data in data_list if re.match(r"\d{4}-\d{2}-\d{2}", data.key)]
        data_list.sort(key=lambda x: x.key, reverse=False)
        today = data_list[-1].key
        today_data = json.loads(data_list[-1].value)
        sites = []
        dls = []
        ups = []
        for st in today_data:
            sites.append(st)
            if today_data[st].get('upload'):
                ups.append(str(self.__gb(today_data[st]['upload'])))
            else:
                ups.append("0")

            if today_data[st].get('download'):
                dls.append(str(self.__gb(today_data[st]['download'])))
            else:
                dls.append("0")
            
        # logger.info(sites)
        # logger.info(ups)
        # logger.info(dls)
        return sites,ups,dls

    def __get_inc(self,days):
        data_list: List[PluginData] = self.get_data(plugin_id='SiteStatistic')
        if not data_list:
            return {}
        # 取key符合日期格式的数据
        data_list = [data for data in data_list if re.match(r"\d{4}-\d{2}-\d{2}", data.key)]
        # logger.info(data_list)
        # 按日期倒序排序
        # data_list.sort(key=lambda x: x.key, reverse=True)
        data_list.sort(key=lambda x: x.key, reverse=False)
        # 今天的日期
        today = data_list[-1].key
        # logger.info(today)
        # 数据按时间降序排序
        datas = [json.loads(data.value) for data in data_list if ObjectUtils.is_obj(data.value)]
        # logger.info(datas)
        dates = [dat.key for dat in data_list][1:]
        # logger.info(dates)
        incs=[]
        for i in range(len(datas)-1):
            inc_data = {}
            for site, data in datas[i+1].items():
                inc = self.__sub_dict(data, datas[i].get(site))
                if inc:
                    inc_data[site] = inc
            incs.append(inc_data)
        # logger.info(incs)
        
        sites_daily_up = {}
        for today in incs:
            for site in today:
                if site not in sites_daily_up:
                    sites_daily_up[site]= []

        for today in incs:
            for site in sites_daily_up:
                if site in today:
                    sites_daily_up[site].append( self.__gb(today[site]['upload']))
                else:
                    sites_daily_up[site].append(0)
        # for k in sites_daily_up:
            # logger.info(f'{k,len(sites_daily_up[k])}')
        
        if len(dates) > days:
            dts = dates[-days:]
            vals = []
            for st in sites_daily_up:
                st_val = {
                    'name':st,
                    'data': sites_daily_up[st][-days:]
                }
                vals.append(st_val)   
            return dts,vals
        else:
            dts = dates
            vals = []
            for st in sites_daily_up:
                st_val = {
                    'name':st,
                    'data': sites_daily_up[st]
                }
                vals.append(st_val)   
            return dts,vals

    def get_page(self) -> List[dict]:
        sites,ups,dls = self.__get_sum()
        dts,vals = self.__get_inc(15)

        today_elements = [
                # 上传量图表
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'md': 12,
                        # 'style':"border-radius: 21px;background: #ffffe6;box-shadow:  8px 8px 9px #99998a, -8px -8px 9px #ffffff;"
                    },
                    'content': [
                        {
                            'component': 'VApexChart',
                            'props': {
                                'height': 500,
                                'options': {
                                    'chart': {
                                        'type': 'bar',
                                        'stacked':True,
                                    },  
                                    'title': {
                                        'text': f'15天上传统计(G)'
                                    },
                  
                                    'dataLabels': {
                                        'enabled': False,
                                        },

                                    'labels':dts                    
                                },
                                'series': vals,
                            }
                        },
                        
                    ]
                },
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'md': 12,
                        # 'style':"border-radius: 21px;background: #ffffe6;box-shadow:  8px 8px 9px #99998a, -8px -8px 9px #ffffff;"
                    },
                    'content': [
                        {
                            'component': 'VApexChart',
                            'props': {
                                'height': 300,
                                'options': {
                                    'chart': {
                                        'type': 'bar',
                                        # 'stacked': True,
                                        # 'stackType': '100%',
                                    },  
                                    'title': {
                                        'text': f'上传下载总和'
                                    },
                  
                                    'dataLabels': {
                                        'enabled': False,
                                    },
                                    

                                    'labels':sites,   
                                    
                                    # 'yaxis':{
                                    #     'logarithmic': True,
                                    #     'logBase':50,
                                    # },
                                    
                                                  
                                },

                                
                                'series': [
                                    {
                                        'name':'upload',
                                        'data': ups,
                                    },
                                    {
                                        'name':'download',
                                        'data': dls,
                                    }
                                ],
                            }
                        },
                    ]
                },
                
                
            ]
        return today_elements

    def stop_service(self):
        """
        退出插件
        """
        pass
