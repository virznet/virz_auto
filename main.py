import os
import random
import time
import requests
import json
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

# 1. 환경 변수 설정 (GitHub Secrets에서 불러옴)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
WP_USERNAME = os.environ.get('WP_USERNAME')
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD')
WP_BASE_URL = "https://virz.net" 

class NaverScraper:
    """네이버 뉴스 및 블로그 랭킹 수집 클래스"""
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        }

    def get_news_ranking(self, section_id):
        url = f"https://news.naver.com/main/ranking/popularDay.naver?sectionId={section_id}"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            titles = soup.select(".rankingnews_list .list_title")
            return [t.text.strip() for t in titles[:10]]
        except:
            return []

    def get_blog_hot_topics(self):
        url = "https://section.blog.naver.com/HotTopicList.naver"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            topics = soup.select(".list_hottopic .desc")
            return [t.text.strip() for t in topics[:10]]
        except:
            return []

def expand_title(keyword, category):
    """키워드를 매력적인 롱테일 제목으로 확장"""
    data = {
        "경제/비즈니스": {
            "targets": ["직장인", "재테크족", "사회초년생"],
            "scenarios": ["실질적인 변화", "2026년 정책 분석", "놓치면 안 될 혜택"],
            "suffixes": ["가이드", "핵심 요약", "주의사항"]
        },
        "IT/테크": {
            "targets": ["얼리어답터", "IT 종사자", "학생"],
            "scenarios": ["사용 후기", "스펙 비교", "할인 꿀팁"],
            "suffixes": ["완벽 가이드", "추천 리스트", "솔직 리뷰"]
        },
        "패션/뷰티/리빙": {
            "targets": ["패션 피플", "그루밍족", "자취생", "신혼부부"],
            "scenarios": ["올해 유행 스타일", "가성비 추천템", "공간 활용법"],
            "suffixes": ["코디 제안", "트렌드 리포트", "꿀템 리뷰"]
        }
    }.get(category, {
        "targets": ["누구나", "관심 있는 분들"],
        "scenarios": ["알아야 할 정보", "최신 소식"],
        "suffixes": ["정리", "근황"]
    })

    t, s, sx = random.choice(data["targets"]), random.choice(data["scenarios"]), random.choice(data["suffixes"])
    templates = [
        f"[{t} 필독] {keyword} {s} {sx}",
        f"{keyword} {s}, {t}이 꼭 알아야 할 {sx}",
        f"{t}을 위한 {keyword} {sx}: {s} 포함"
    ]
    return random.choice(templates)

def generate_content(title, category):
    """Gemini API를 이용한 본문 생성 (gemini-2.5-flash-preview-09-2025)"""
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    system_prompt = f"당신은 {category} 분야 전문 블로거입니다. virz.net 블로그에 올릴 SEO 최적화된 블로그 글을 작성하세요."
    user_query = f"""
    제목: {title}
    
    [작성 가이드라인]
    1. 서론: 독자의 관심을 끄는 도입부.
    2. 본론: 3개의 핵심 소주제(H2 헤딩 사용)로 상세 설명.
    3. 표: 데이터나 특징을 비교하는 마크다운 표(Table)를 반드시 1개 포함.
    4. 결론: 내용을 요약하고 독자에게 마지막 조언.
    5. 말투: 친절하고 전문적인 구어체 (~해요).
    6. 형식: HTML 태그(h2, p, table, tr, td 등)를 사용하여 작성 (마크다운이 아닌 HTML로 출력).
    
    주의: "AI로서 작성한 글입니다"와 같은 문구는 포함하지 마세요.
    """
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }
    
    # 지수 백오프 적용: 1s, 2s, 4s, 8s, 16s
    delays = [1, 2, 4, 8, 16]
    
    for delay in delays:
        try:
            response = requests.post(url, json=payload, timeout=60)
            if response.status_code == 200:
                result = response.json()
                text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text')
                if text:
                    return text
            elif response.status_code in [429, 500, 502, 503, 504]:
                time.sleep(delay)
                continue
            else:
                print(f"API 오류: {response.status_code} - {response.text}")
                break
        except Exception:
            time.sleep(delay)
            continue
            
    print(f"콘텐츠 생성 실패: 모든 재시도를 소진했습니다.")
    return None

def post_to_wp(title, content):
    """워드프레스 REST API 업로드"""
    url = f"{WP_BASE_URL}/wp-json/wp/v2/posts"
    payload = {
        "title": title,
        "content": content,
        "status": "publish"
    }
    try:
        res = requests.post(
            url,
            auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
            json=payload,
            timeout=20
        )
        return res.status_code == 201
    except:
        return False

def main():
    scraper = NaverScraper()
    print("1. 키워드 수집 시작...")
    
    jobs = [
        ("101", "경제/비즈니스"),
        ("105", "IT/테크"),
        ("103", "패션/뷰티/리빙"),
        (None, "일반/생활")
    ]
    
    candidates = []
    for sid, cat in jobs:
        titles = scraper.get_news_ranking(sid) if sid else scraper.get_blog_hot_topics()
        for t in titles[:5]:
            candidates.append({"kw": t, "cat": cat})
        time.sleep(1)

    if not candidates:
        print("수집된 키워드가 없습니다.")
        return
        
    selected = random.sample(candidates, min(len(candidates), 10))
    
    print(f"2. {len(selected)}개의 글을 오전 7시~9시 사이에 랜덤하게 발행합니다.")
    
    # 2시간(7200초) 범위 내 무작위 발행 시간 계산
    total_seconds = 2 * 60 * 60
    posting_times = sorted([random.randint(0, total_seconds) for _ in range(len(selected))])
    
    last_wait = 0
    for i, item in enumerate(selected):
        wait_for_next = posting_times[i] - last_wait
        if wait_for_next > 0:
            print(f"[{i+1}/10] 다음 발행까지 {wait_for_next}초 대기 중...")
            time.sleep(wait_for_next)
        
        final_title = expand_title(item['kw'], item['cat'])
        print(f"본문 생성 중: {final_title}")
        body = generate_content(final_title, item['cat'])
        
        if body and post_to_wp(final_title, body):
            print(f"✅ 발행 완료: {final_title}")
        else:
            print(f"❌ 발행 실패: {final_title}")
            
        last_wait = posting_times[i]

if __name__ == "__main__":
    main()
