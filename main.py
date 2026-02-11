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
            # [단독], [포토] 등 불필요한 머리말 제거 후 수집
            cleaned_titles = []
            for t in titles[:10]:
                text = t.text.strip()
                if ']' in text[:10]:
                    text = text.split(']', 1)[-1].strip()
                cleaned_titles.append(text)
            return cleaned_titles
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

def generate_content(raw_keyword, category):
    """Gemini API를 이용한 제목, 본문, 요약, 태그 통합 생성"""
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
제공된 키워드를 분석하여 독자에게 실질적인 가치를 주는 고품질 블로그 글을 작성하세요.

[필수 준수 사항]
1. 주제 집중: 오직 제공된 하나의 키워드에 대해서만 깊이 있게 작성하세요. 다른 무관한 주제를 섞지 마세요.
2. 인사말 금지: '안녕하세요', '전문 블로거입니다' 같은 도입부나 자기소개를 절대 하지 마세요. 바로 본론의 정보로 시작합니다.
3. 분량 및 품질: 글자 수 공백 제외 3,000자 이상의 매우 상세한 내용을 작성하세요. 전문 용어 설명과 구체적인 예시를 포함하세요.
4. 구텐베르크 블록 형식: 워드프레스 에디터가 인식할 수 있도록 HTML 주석 블록을 사용하세요.
   - 예: <!-- wp:heading {{"level":2}} --><h2>소주제</h2><!-- /wp:heading -->
   - 예: <!-- wp:paragraph --><p>내용...</p><!-- /wp:paragraph -->
   - 예: <!-- wp:list --><ul><li>...</li></ul><!-- /wp:list -->
5. SEO 제목: 클릭을 유발하면서도 검색 최적화된 매력적인 제목을 새로 만드세요.
6. 태그: 관련 태그 5개를 쉼표(,)로 구분하여 생성하세요.
"""
    
    user_query = f"""
원본 키워드: {raw_keyword}

다음 형식의 JSON으로만 응답하세요:
{{
  "title": "새로 생성한 매력적인 SEO 제목",
  "content": "워드프레스 구텐베르크 블록 형식이 적용된 3,000자 이상의 상세 본문",
  "excerpt": "글의 핵심 내용을 요약한 1~2문장의 요약글",
  "tags": "태그1,태그2,태그3,태그4,태그5"
}}
"""
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    delays = [1, 2, 4, 8, 16]
    for delay in delays:
        try:
            response = requests.post(url, json=payload, timeout=120)
            if response.status_code == 200:
                result = response.json()
                text_content = result['candidates'][0]['content']['parts'][0]['text']
                return json.loads(text_content)
            elif response.status_code in [429, 500, 502, 503, 504]:
                time.sleep(delay)
                continue
            else:
                print(f"API 오류: {response.status_code} - {response.text}", flush=True)
                break
        except Exception as e:
            print(f"콘텐츠 생성 중 예외 발생: {e}", flush=True)
            time.sleep(delay)
            continue
    return None

def post_to_wp(content_data):
    """워드프레스 REST API 업로드"""
    base_url = WP_BASE_URL.rstrip('/')
    url = f"{base_url}/wp-json/wp/v2/posts"
    
    auth_str = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    payload = {
        "title": content_data.get('title', ''),
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
    print("🚀 [1단계] 키워드 수집 및 정제 시작...", flush=True)
    
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
        print("❌ 수집된 키워드가 없습니다.", flush=True)
        return
        
    if IS_TEST:
        print("\n🧪 [테스트 모드] 1개 즉시 발행 시도", flush=True)
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
        
        print(f"📝 콘텐츠 분석 및 생성 중: {item['kw']}", flush=True)
        content_data = generate_content(item['kw'], item['cat'])
        
        if content_data and content_data.get('title'):
            print(f"📌 최종 제목: {content_data['title']}", flush=True)
            if post_to_wp(content_data):
                print(f"✅ 발행 완료: {content_data['title']}", flush=True)
            else:
                print(f"❌ 워드프레스 발행 실패", flush=True)
        else:
            print(f"❌ AI 콘텐츠 생성 실패", flush=True)
            
        last_wait = posting_times[i]

    print("\n🎉 모든 자동 포스팅 작업이 성공적으로 종료되었습니다.", flush=True)

if __name__ == "__main__":
    main()
