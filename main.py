import os
import random
import time
import requests
import json
import base64
import re
import io
import sys
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from PIL import Image

# 콘솔 출력 시 한글 깨짐 방지 설정
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# ==========================================
# 1. 환경 변수 및 설정
# ==========================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
WP_USERNAME = os.environ.get('WP_USERNAME', '').strip()
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD', '').replace(' ', '').strip()
# [수정] URL은 마크다운 형식이 아닌 순수 문자열이어야 합니다.
WP_BASE_URL = "https://virz.net" 

# TEST_MODE 판단 로직 (환경 변수가 'true'이거나 secret이 'true'로 설정된 경우)
test_mode_raw = str(os.environ.get('TEST_MODE', 'false')).strip().lower()
IS_TEST = test_mode_raw in ['true', '1', 't', 'yes', 'y', '***'] # 시크릿 마스킹 대비

# ==========================================
# 2. 유틸리티 함수
# ==========================================
def clean_json_string(text):
    """AI 응답에서 마크다운 코드 블록 등을 제거하고 순수 JSON만 추출"""
    text = text.strip()
    # 마크다운 블록 제거
    if text.startswith("```"):
        text = re.sub(r'^`{3}(?:json)?\s*', '', text)
        text = re.sub(r'\s*`{3}$', '', text)
    return text.strip()

# ==========================================
# 3. 데이터 수집 로직
# ==========================================
def load_external_links():
    file_path = "links.json"
    default_links = [{"title": "virz.net", "url": "[https://virz.net](https://virz.net)"}]
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if data else default_links
        except Exception:
            return default_links
    return default_links

class TrendScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def get_naver_news_titles(self, url):
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            res.encoding = res.apparent_encoding
            soup = BeautifulSoup(res.text, 'html.parser')
            titles = [t.text.strip() for t in soup.select(".sa_text_strong") if t.text.strip()]
            return list(dict.fromkeys(titles))[:10]
        except Exception as e:
            print(f"⚠️ 스크래핑 오류: {e}")
            return []

# ==========================================
# 4. 워드프레스 & 이미지 처리
# ==========================================
def get_recent_posts():
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except Exception: pass
    return []

def generate_image_process(prompt):
    url = f"[https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key=](https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key=){GEMINI_API_KEY}"
    final_prompt = f"Professional photography for: {prompt}. High resolution, cinematic. NO TEXT."
    payload = {"instances": [{"prompt": final_prompt}], "parameters": {"sampleCount": 1}}
    
    # 지수 백오프 기반 재시도 (최대 5회)
    for i, delay in enumerate([1, 2, 4, 8, 16]):
        try:
            response = requests.post(url, json=payload, timeout=150)
            if response.status_code == 200:
                b64_data = response.json()['predictions'][0]['bytesBase64Encoded']
                return base64.b64decode(b64_data)
        except Exception:
            pass
        time.sleep(delay)
    return None

def upload_to_wp_media(img_data):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=feat_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201: return res.json()['id']
    except Exception: pass
    return None

# ==========================================
# 5. 스마트 콘텐츠 생성
# ==========================================
def generate_article(keyword, category, internal_posts, user_links):
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){model_id}:generateContent?key={GEMINI_API_KEY}"
    
    internal_ref = "내 블로그 추천글:\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in internal_posts[:2]])
    user_ext_ref = "외부 링크:\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in user_links[:2]])

    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 상세하고 사람이 직접 쓴 듯한 블로그 글을 작성하세요.

[필수 사항: 워드프레스 구텐베르크 블록 형식]
- 모든 콘텐츠는 워드프레스 구텐베르크(Gutenberg) 블록 주석으로 감싸야 합니다.
- 문단: <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph -->
- 제목(H2): <!-- wp:heading --><h2>제목</h2><!-- /wp:heading -->
- 제목(H3): <!-- wp:heading {{"level":3}} --><h3>제목</h3><!-- /wp:heading -->
- 버튼: <!-- wp:buttons --><div class="wp-block-buttons"><!-- wp:button --><div class="wp-block-button"><a class="wp-block-button__link" href="URL">텍스트</a></div><!-- /wp:button --></div><!-- /wp:buttons -->

[절대 엄수 사항: 순서 표기 금지]
1. 본문의 소제목(H2, H3, H4) 및 리스트 작성 시, 순서를 나타내는 모든 숫자와 문자를 제외하세요.
   - 금지 예시: '1.', '2.', '첫째,', 'A.', 'Step 1' 등 나열식 기호 금지.
2. 인사말 없이 즉시 본론으로 시작하세요.
3. 한 문단은 3줄 이내로 짧게 작성하세요.

JSON 응답 키: 'title', 'content', 'excerpt', 'tags', 'image_prompt'.
"""
    
    payload = {
        "contents": [{"parts": [{"text": f"키워드: {keyword}\n{internal_ref}\n{user_ext_ref}"}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "content": {"type": "STRING"},
                    "excerpt": {"type": "STRING"},
                    "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "image_prompt": {"type": "STRING"}
                },
                "required": ["title", "content", "excerpt", "tags", "image_prompt"]
            }
        }
    }
    
    # 지수 백오프 기반 재시도 (최대 5회)
    for i, delay in enumerate([1, 2, 4, 8, 16]):
        try:
            res = requests.post(url, json=payload, timeout=180)
            if res.status_code == 200:
                raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                clean_text = clean_json_string(raw_text)
                return json.loads(clean_text)
            else:
                print(f"⚠️ API 오류 (상태코드: {res.status_code})")
        except Exception as e:
            print(f"⚠️ 시도 {i+1} 실패: {e}")
        
        if i < 4: time.sleep(delay)
    
    return None

# ==========================================
# 6. 워드프레스 발행 로직
# ==========================================
def post_article(data, mid):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    # 태그 처리 및 ID 변환
    tag_ids = []
    tags_raw = data.get('tags', [])
    if isinstance(tags_raw, list):
        for tname in tags_raw:
            try:
                # 태그 검색
                r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth, timeout=10)
                tid = None
                if r.status_code == 200:
                    tags_data = r.json()
                    tid = next((t['id'] for t in tags_data if t['name'].lower() == tname.lower()), None)
                
                # 태그가 없으면 생성
                if not tid:
                    cr = requests.post(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags", auth=auth, json={"name": tname}, timeout=10)
                    if cr.status_code == 201:
                        tid = cr.json()['id']
                
                if tid: tag_ids.append(tid)
            except: continue

    payload = {
        "title": data.get('title', '제목 없음'), 
        "content": data.get('content', ''), 
        "excerpt": data.get('excerpt', ''),
        "tags": tag_ids,
        "featured_media": mid, 
        "status": "publish"
    }
    
    try:
        res = requests.post(url, auth=auth, json=payload, timeout=40)
        if res.status_code != 201:
            print(f"⚠️ 발행 실패 상세: {res.status_code} - {res.text}")
        return res.status_code == 201
    except Exception as e:
        print(f"⚠️ 포스팅 도중 예외 발생: {e}")
    return False

# ==========================================
# 7. 메인 실행부
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ API 키 누락")
        return

    print(f"DEBUG: 현재 TEST_MODE 환경 변수 값 = '{os.environ.get('TEST_MODE', 'NOT_SET')}'")
    
    if IS_TEST:
        print("🧪 테스트 모드 활성화: 즉시 실행합니다.")
    else:
        start_delay = random.randint(0, 3300) 
        print(f"⏳ 랜덤 분 발행 대기: {start_delay // 60}분...")
        time.sleep(start_delay)

    user_links = load_external_links()
    recent_posts = get_recent_posts()
    scraper = TrendScraper()
    
    print("🚀 프로세스 시작...")
    
    news_sections = [
        "[https://news.naver.com/section/102](https://news.naver.com/section/102)",
        "[https://news.naver.com/section/105](https://news.naver.com/section/105)",
        "[https://news.naver.com/breakingnews/section/103/241](https://news.naver.com/breakingnews/section/103/241)", 
        "[https://news.naver.com/breakingnews/section/103/237](https://news.naver.com/breakingnews/section/103/237)", 
        "[https://news.naver.com/breakingnews/section/103/376](https://news.naver.com/breakingnews/section/103/376)", 
        "[https://news.naver.com/breakingnews/section/103/242](https://news.naver.com/breakingnews/section/103/242)"
    ]
    
    pool = []
    for url in news_sections:
        titles = scraper.get_naver_news_titles(url)
        for t in titles: pool.append(t)
    
    if not pool: 
        print("⚠️ 수집된 데이터 없음")
        return
    
    keyword = random.choice(pool)
    print(f"📝 대상 키워드: {keyword}")
    
    data = generate_article(keyword, "트렌드 뉴스", recent_posts, user_links)
    if not data: 
        print("⚠️ 콘텐츠 생성 최종 실패")
        return
    
    mid = None
    if data.get('image_prompt'):
        print("🎨 이미지 생성 중...")
        img_data = generate_image_process(data['image_prompt'])
        if img_data: mid = upload_to_wp_media(img_data)
    
    if post_article(data, mid):
        print(f"✅ 발행 성공: {data.get('title')}")
    else:
        print("❌ 발행 최종 실패")

if __name__ == "__main__":
    main()
