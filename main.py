import os
import random
import time
import requests
import json
import base64
import re
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
    
    # 현재 날짜 정보 (배경 지식으로만 제공)
    current_date = "2026년 2월 11일"
    
    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
참고용 현재 날짜는 {current_date}입니다. 이 날짜는 정보의 최신성을 판단하는 기준으로만 사용하세요.

[필수 준수 사항]
1. 주제 집중: 오직 제공된 하나의 키워드에 대해서만 깊이 있게 작성하세요.
2. 날짜 언급 금지: 본문 내에 '오늘은 {current_date}입니다' 혹은 '오늘'과 같은 구체적인 날짜 표현을 직접적으로 언급하지 마세요. 
3. 인사말 금지: 도입부 자기소개나 독자 인사를 절대 하지 마세요. 바로 본론의 정보로 시작합니다.
4. 분량: 공백 제외 3,000자 이상의 매우 상세한 내용을 작성하세요. 
5. 구텐베르크 블록 형식: 워드프레스 에디터가 인식할 수 있도록 HTML 주석 블록을 정확하게 사용하세요.
   - 예: <!-- wp:heading {{"level":2}} --><h2>소주제</h2><!-- /wp:heading -->
   - 예: <!-- wp:paragraph --><p>내용...</p><!-- /wp:paragraph -->
6. SEO 제목: 매력적이고 검색에 유리한 제목을 새로 만드세요.
7. 태그: 관련 태그 5개를 쉼표(,)로 구분하여 생성하세요.
"""
    
    user_query = f"""
원본 키워드: {raw_keyword}

다음 형식의 JSON으로만 응답하세요:
{{
  "title": "SEO 최적화 제목",
  "content": "구텐베르크 블록 형식이 적용된 3,000자 이상의 본문",
  "excerpt": "핵심 요약 1~2문장",
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
                clean_json = re.sub(r'^```json\s*|\s*```$', '', text_content.strip(), flags=re.MULTILINE)
                return json.loads(clean_json)
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

def get_or_create_tags(base_url, headers, tag_names_str):
    """태그 이름을 ID로 변환 (없으면 생성)"""
    if not tag_names_str:
        return []
    
    tag_names = [t.strip() for t in tag_names_str.split(',') if t.strip()]
    tag_ids = []
    
    for name in tag_names:
        try:
            # 1. 기존 태그 검색
            search_url = f"{base_url}/wp-json/wp/v2/tags?search={name}"
            res = requests.get(search_url, headers=headers, timeout=10)
            existing_tags = res.json()
            
            found = False
            if isinstance(existing_tags, list):
                for et in existing_tags:
                    if et['name'] == name:
                        tag_ids.append(et['id'])
                        found = True
                        break
            
            if not found:
                # 2. 태그가 없으면 생성
                create_url = f"{base_url}/wp-json/wp/v2/tags"
                create_res = requests.post(create_url, headers=headers, json={"name": name}, timeout=10)
                if create_res.status_code in [200, 201]:
                    tag_ids.append(create_res.json()['id'])
                elif create_res.status_code == 400: # 이미 존재하지만 검색에 안걸린 경우 등
                    # 다시 한번 검색 시도
                    res = requests.get(search_url, headers=headers, timeout=10)
                    if res.status_code == 200 and res.json():
                        tag_ids.append(res.json()[0]['id'])

        except Exception as e:
            print(f"태그 처리 중 오류 ({name}): {e}", flush=True)
            
    return tag_ids

def post_to_wp(content_data):
    """워드프레스 REST API 업로드 (태그 ID 필드 사용)"""
    base_url = WP_BASE_URL.rstrip('/')
    url = f"{base_url}/wp-json/wp/v2/posts"
    
    auth_str = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json"
    }

    # 태그 이름을 ID 리스트로 변환
    tag_ids = get_or_create_tags(base_url, headers, content_data.get('tags', ''))

    payload = {
        "title": content_data.get('title', ''),
        "content": content_data.get('content', ''),
        "excerpt": content_data.get('excerpt', ''),
        "tags": tag_ids, # 워드프레스 태그 입력 필드에 적용
        "status": "publish"
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 201:
            return True
        else:
            print(f"⚠️ 워드프레스 응답 오류: {res.status_code} - {res.text}", flush=True)
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
