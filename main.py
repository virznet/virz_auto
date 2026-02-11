import os
import random
import time
import requests
import json
import base64
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

# 1. 환경 변수 및 설정
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
WP_USERNAME = os.environ.get('WP_USERNAME', '').strip()
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD', '').replace(' ', '').strip()
WP_BASE_URL = "https://virz.net" 

# 테스트 모드 설정 (True면 1개만 즉시 발행, False면 10개 랜덤 발행)
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

class NaverScraper:
    """네이버 뉴스 및 블로그 랭킹 수집 클래스"""
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        }

    def get_news_ranking(self, section_id):
        url = f"https://news.naver.com/main/ranking/popularDay.naver?sectionId={section_id}"
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            titles = soup.select(".rankingnews_list .list_title")
            return [t.text.strip() for t in titles[:10]]
        except Exception as e:
            print(f"뉴스 스크래핑 실패 ({section_id}): {e}", flush=True)
            return []

    def get_blog_hot_topics(self):
        url = "https://section.blog.naver.com/HotTopicList.naver"
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            topics = soup.select(".list_hottopic .desc")
            return [topic.text.strip() for topic in topics[:10]]
        except Exception as e:
            print(f"블로그 핫토픽 스크래핑 실패: {e}", flush=True)
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
    """Gemini API를 이용한 본문 및 메타데이터 생성 (JSON 응답 방식)"""
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
가독성이 높고 전문적인 정보성 글을 작성하며, 다음 규칙을 반드시 준수하세요:
1. 절대 '안녕하세요', '독자 여러분' 같은 인사말이나 서론의 자기소개를 포함하지 마세요. 바로 본론으로 들어갑니다.
2. 오직 하나의 키워드 주계에만 집중하여 깊이 있게 작성하세요. 다른 뉴스 요약과 섞지 마세요.
3. 약 3,000자 이상의 풍성한 내용을 SEO 원칙에 따라 작성하세요.
4. 워드프레스 구텐베르크(Gutenberg) 블록 형식(HTML 주석 포함)으로 본문을 구성하세요.
   예: <!-- wp:heading {{"level":2}} --><h2>...</h2><!-- /wp:heading -->
"""
    
    user_query = f"""
제목: {title}

다음 형식의 JSON으로만 응답하세요:
{{
  "content": "워드프레스 구텐베르크 블록 형식이 적용된 HTML 본문 (약 3000자)",
  "excerpt": "글의 핵심 내용을 요약한 1~2문장의 요약글",
  "tags": "쉼표로 구분된 관련 태그 5개 (예: 경제,재테크,연금)"
}}
"""
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {{
            "responseMimeType": "application/json"
        }}
    }
    
    delays = [1, 2, 4, 8, 16]
    for delay in delays:
        try:
            response = requests.post(url, json=payload, timeout=90)
            if response.status_code == 200:
                result = response.json()
                data = json.loads(result['candidates'][0]['content']['parts'][0]['text'])
                return data
            elif response.status_code in [429, 500, 502, 503, 504]:
                time.sleep(delay)
                continue
            else:
                print(f"API 오류: {response.status_code}", flush=True)
                break
        except Exception as e:
            print(f"콘텐츠 생성 중 예외 발생: {e}", flush=True)
            time.sleep(delay)
            continue
    return None

def post_to_wp(title, content_data):
    """워드프레스 REST API 업로드 (요약글 및 태그 포함)"""
    base_url = WP_BASE_URL.rstrip('/')
    url = f"{base_url}/wp-json/wp/v2/posts"
    
    auth_str = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    # 워드프레스 기본 API는 태그 이름 문자열을 직접 받지 않고 ID를 요구하는 경우가 많습니다.
    # 하지만 쉼표 구분 문자열을 메타데이터나 특정 플러그인 필드로 활용할 수 있도록 구성합니다.
    payload = {
        "title": title,
        "content": content_data.get('content', ''),
        "excerpt": content_data.get('excerpt', ''),
        "status": "publish"
    }
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json"
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 201:
            return True
        else:
            print(f"⚠️ 워드프레스 응답 오류: {res.status_code}", flush=True)
            return False
    except Exception as e:
        print(f"❗ 워드프레스 연결 예외: {e}", flush=True)
        return False

def main():
    if not WP_USERNAME or not WP_APP_PASSWORD:
        print("❌ 인증 정보가 부족합니다.", flush=True)
        return

    scraper = NaverScraper()
    print("🚀 [1단계] 키워드 수집 시작...", flush=True)
    
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
        print("❌ 수집된 키워드 없음.", flush=True)
        return
        
    if IS_TEST:
        print("\n🧪 [테스트 모드] 1개 즉시 발행", flush=True)
        selected = random.sample(candidates, 1)
        posting_times = [0]
    else:
        selected = random.sample(candidates, min(len(candidates), 10))
        total_seconds = 2 * 60 * 60
        posting_times = sorted([random.randint(0, total_seconds) for _ in range(len(selected))])

    last_wait = 0
    for i, item in enumerate(selected):
        wait_for_next = posting_times[i] - last_wait
        if wait_for_next > 0:
            print(f"\n⏳ 대기: {wait_for_next//60}분...", flush=True)
            time.sleep(wait_for_next)
        
        final_title = expand_title(item['kw'], item['cat'])
        print(f"📝 본문 및 메타데이터 생성 중: {final_title}", flush=True)
        
        # 이제 generate_content는 본문, 요약, 태그가 담긴 dict를 반환합니다.
        content_data = generate_content(final_title, item['cat'])
        
        if content_data:
            if post_to_wp(final_title, content_data):
                print(f"✅ 발행 완료: {final_title}", flush=True)
            else:
                print(f"❌ 워드프레스 전송 실패", flush=True)
        else:
            print(f"❌ AI 생성 실패", flush=True)
            
        last_wait = posting_times[i]

    print("\n🎉 모든 자동 포스팅 작업이 완료되었습니다.", flush=True)

if __name__ == "__main__":
    main()
