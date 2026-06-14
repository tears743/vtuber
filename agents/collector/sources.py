"""
Layer 1: 数据采集 - OpenCLI 封装

通过调用本地编译的 OpenCLI 获取各平台数据
"""
import json
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class OpenCLIRunner:
    """OpenCLI 命令执行器"""
    
    def __init__(self, binary: str, output_format: str = "json"):
        self.binary = binary
        self.output_format = output_format
    
    def run(self, command: str, timeout: int = 120) -> dict | list | None:
        """
        执行 opencli 命令并返回解析后的 JSON
        
        Args:
            command: 不含 binary 前缀的命令，如 "weibo hot -f json"
            timeout: 超时秒数
        
        Returns:
            解析后的 JSON 数据，失败返回 None
        """
        full_cmd = f"{self.binary} {command}"
        logger.info(f"[opencli] 执行: {full_cmd}")
        
        try:
            result = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
            )
            
            if result.returncode != 0:
                logger.error(f"[opencli] 命令失败 (code={result.returncode}): {result.stderr[:500]}")
                return None
            
            output = result.stdout.strip()
            if not output:
                logger.warning("[opencli] 命令返回空输出")
                return None
            
            return json.loads(output)
        
        except subprocess.TimeoutExpired:
            logger.error(f"[opencli] 命令超时 ({timeout}s): {command}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[opencli] JSON 解析失败: {e}")
            # 保存原始输出用于调试
            logger.debug(f"[opencli] 原始输出: {result.stdout[:1000]}")
            return None
        except Exception as e:
            logger.error(f"[opencli] 未知错误: {e}")
            return None


class WeiboCollector:
    """微博数据采集"""
    
    def __init__(self, runner: OpenCLIRunner, data_dir: Path):
        self.runner = runner
        self.data_dir = data_dir / "weibo"
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch_hot(self) -> list | None:
        """获取微博热搜榜"""
        data = self.runner.run("weibo hot -f json")
        if data:
            self._save(data, "hot")
            logger.info(f"[weibo] 获取热搜 {len(data) if isinstance(data, list) else '?'} 条")
        return data
    
    def search(self, keyword: str, count: int = 20) -> list | None:
        """搜索微博"""
        data = self.runner.run(f'weibo search "{keyword}" --count {count} -f json')
        return data
    
    def get_post(self, post_id: str) -> dict | None:
        """获取单条微博详情"""
        return self.runner.run(f"weibo post {post_id} -f json")
    
    def _save(self, data, name: str):
        """保存数据到文件"""
        today = datetime.now().strftime("%Y-%m-%d")
        ts = datetime.now().strftime("%H%M")
        filepath = self.data_dir / f"{today}_{name}_{ts}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"[weibo] 数据已保存: {filepath}")


class DouyinCollector:
    """抖音数据采集"""
    
    def __init__(self, runner: OpenCLIRunner, data_dir: Path):
        self.runner = runner
        self.data_dir = data_dir / "douyin"
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch_hashtag_hot(self) -> list | None:
        """获取抖音热点话题"""
        data = self.runner.run("douyin hashtag hot -f json")
        if data:
            self._save(data, "hashtag_hot")
            logger.info(f"[douyin] 获取热点话题 {len(data) if isinstance(data, list) else '?'} 条")
        return data
    
    def search(self, query: str, count: int = 20) -> list | None:
        """搜索抖音视频"""
        data = self.runner.run(f'douyin search "{query}" --count {count} -f json')
        return data
    
    def _save(self, data, name: str):
        today = datetime.now().strftime("%Y-%m-%d")
        ts = datetime.now().strftime("%H%M")
        filepath = self.data_dir / f"{today}_{name}_{ts}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class AINewsCollector:
    """AI 科技新闻采集"""
    
    def __init__(self, runner: OpenCLIRunner, data_dir: Path):
        self.runner = runner
        self.data_dir = data_dir / "ai_news"
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch_hf_papers(self) -> list | None:
        """获取 HuggingFace 热门论文"""
        data = self.runner.run("hf top -f json")
        if data:
            self._save(data, "hf_papers")
            logger.info(f"[ai_news] HF论文 {len(data) if isinstance(data, list) else '?'} 条")
        return data
    
    def fetch_hf_models(self) -> list | None:
        """获取 HuggingFace 热门模型"""
        data = self.runner.run("hf models --sort trending -f json")
        if data:
            self._save(data, "hf_models")
            logger.info(f"[ai_news] HF模型 {len(data) if isinstance(data, list) else '?'} 条")
        return data
    
    def fetch_github_trending(self) -> list | None:
        """获取 GitHub Trending（通用浏览器命令）"""
        data = self.runner.run("browser extract https://github.com/trending -f json", timeout=60)
        if data:
            self._save(data, "github_trending")
            logger.info(f"[ai_news] GitHub Trending 获取完成")
        return data
    
    def _save(self, data, name: str):
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = self.data_dir / f"{today}_{name}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
