import os
import random
import time
import requests
import json
import base64
import re
import io
import sys
import xml.etree.ElementTree as ET
from requests.auth import HTTPBasicAuth
from PIL import Image
from datetime import datetime, timedelta, timezone

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
WP_BASE_URL = os.environ.get('WP_BASE_URL', '').strip() 

RSS_URLS = [
    "https://virz.net/feed",
    "https://121913.tistory.com/rss",
    "https://exciting.tistory.com/rss",
    "https://sleepyourmoney.net/feed",
    "https://rss.blog.naver.com/moviepotal.xml"
]

# [수정] 테스트 모드 설정 로직 강화
# 환경 변수 TEST_MODE가 존재하고, 그 값이 'true'인 경우에만 True로 설정
# .strip()을 통해 보이지 않는 공백을 제거하고 .lower()로 대소문자 무시
raw_test_env = os.environ.get('TEST_MODE', 'false').strip().lower()
IS_TEST = (raw_test_env == 'true')

# 만약 GitHub Actions 설정이 계속 말을 안 듣는다면, 
# 아래 줄의 주석(#)을 제거하여 강제로 True를 만드세요.
# 파이썬은 대문자 'True'를 사용해야 합니다. (소문자 true는 에러 발생)
# IS_TEST = True 

# ==========================================
# 2. 공통 유틸리티 (Tier 1 최적화 지수 백오프)
# ==========================================
def safe_api_call(url, payload, method="POST", timeout=300):
    """지수 백오프를 적용한 안전한 API 호출 함수"""
    delays = [1, 2, 4, 8, 16] 
    for i in range(len(delays)):
        try:
            if method == "POST":
                res = requests.post(url, json=payload, timeout=timeout)
            else:
                res = requests.get(url, timeout=timeout)
            
            if res.status_code == 200:
                return res
            elif res.status_code == 429:
                print(f"⚠️ 할당량 일시 초과(429). {delays[i]}초 후 다시 시도합니다...")
                time.sleep(delays[i])
            else:
                print(f"⚠️ API 오류 (HTTP {res.status_code}). {delays[i]}초 후 다시 시도합니다...")
                time.sleep(delays[i])
        except Exception as e:
            print(f"⚠️ 요청 중 예외 발생: {e}. {delays[i]}초 후 다시 시도합니다...")
            time.sleep(delays[i])
    return None

# ==========================================
# 3. 다분야 롱테일 키워드 생성 엔진
# ==========================================
class VersatileKeywordEngine:
    def __init__(self, api_key):
        self.api_key = api_key
        self.model = "gemini-1.5-flash-latest" 
        self.categories = {
            "건강정보": ["만성 질환 예방", "필수 영양제 가이드", "심리 상담", "재활 운동", "수면 장애 극복"],
            "복지정보": ["정부 지원금 신청", "시니어 복지", "청년 주거 지원", "육아 휴직 활용", "장애인 고용 지원"],
            "생활정보": ["세무 상식", "법률 상식", "친환경 살림", "저축 방법", "요리 비법"]
        }

    def generate_target(self, current_date):
        selected_cat = random.choice(list(self.categories.keys()))
        seed_topic = random.choice(self.categories[selected_cat])
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        prompt = f"""당신은 SEO 전문가입니다. 분야 '{selected_cat}'의 주제 '{seed_topic}'와 관련하여 
현재 시점에 유효한 구체적인 '롱테일 키워드' 1개를 생성하세요. 

[지침]
1. 연도(2026년 등)나 특정 날짜 정보를 절대로 포함하지 마세요.
2. 결과는 반드시 JSON 형식으로만 응답하세요.
{{
  "keyword": "연도 정보가 없는 롱테일 키워드",
  "category": "{selected_cat}"
}}"""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        
        res = safe_api_call(url, payload)
        if res:
            try:
                text = res.json()['candidates'][0]['content']['parts'][0]['text']
                return json.loads(text)
            except: pass
        
        return {"keyword": f"{seed_topic} 상세 가이드", "category": selected_cat}

# ==========================================
# 4. 워드프레스 및 이미지 처리 & 링크 수집
# ==========================================
def get_rss_links(rss_urls):
    rss_links = []
    print(f"📡 RSS 피드에서 외부 링크 수집 중...", flush=True)
    for url in rss_urls:
        try:
            response = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code == 200:
                content = response.text
                content_clean = re.sub(r'^[^\<]*', '', content) 
                try:
                    root = ET.fromstring(content_clean.encode('utf-8'))
                    for item in root.findall(".//item")[:5]:
                        title = item.find("title").text if item.find("title") is not None else ""
                        link = item.find("link").text if item.find("link") is not None else ""
                        if title and link:
                            rss_links.append({"title": title.strip(), "url": link.strip()})
                except:
                    items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)
                    for item in items[:5]:
                        title_match = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
                        link_match = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
                        if title_match and link_match:
                            t = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title_match.group(1)).strip()
                            l = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', link_match.group(1)).strip()
                            rss_links.append({"title": t, "url": l})
        except: pass
    return rss_links

def load_external_links_from_json():
    file_path = "links.json"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return [{"title": "virz.net", "url": "https://virz.net"}]

def get_recent_posts():
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except: return []

def generate_image_process(prompt):
    print(f"🎨 이미지 생성 중...", flush=True)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    final_prompt = f"High-quality commercial photography for: {prompt}. Featuring a Korean person, professional lighting, clean composition. NO TEXT."
    payload = {"instances": [{"prompt": final_prompt}], "parameters": {"sampleCount": 1}}
    
    res = safe_api_call(url, payload, timeout=150)
    if res:
        try:
            result = res.json()
            if 'predictions' in result:
                b64_data = result['predictions'][0]['bytesBase64Encoded']
                raw_bytes = base64.b64decode(b64_data)
                img = Image.open(io.BytesIO(raw_bytes))
                if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                output_buffer = io.BytesIO()
                img.save(output_buffer, format="JPEG", quality=70, optimize=True)
                return output_buffer.getvalue()
        except: pass
    return None

def upload_to_wp_media(img_data):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=auto_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201: return res.json()['id']
    except: pass
    return None

# ==========================================
# 5. 고도화된 콘텐츠 생성 (Gutenberg 최적화)
# ==========================================
def generate_article(target, internal_posts, combined_external_links, current_date):
    keyword = target['keyword']
    category = target['category']
    print(f"🤖 [{category}] 분야 콘텐츠 생성 중: {keyword}", flush=True)
    
    model_id = "gemini-1.5-flash-latest"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    selected_int = random.sample(internal_posts, min(len(internal_posts), 2)) if internal_posts else []
    internal_ref_data = "\n".join([f"제목: {p['title']} | 링크: {p['link']}" for p in selected_int])
    
    selected_ext = random.sample(combined_external_links, min(len(combined_external_links), 3))
    external_ref_data = "\n".join([f"제목: {l['title']} | 링크: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 전문 에디터입니다. 구텐베르크 블록 에디터 방식에 최적화된 글을 작성하세요.
- 분량: 2,500~3,000자 내외의 깊이 있는 내용.
- 날짜 정보 배제: 연도, 월, 일 정보를 제목과 본문에 포함하지 마세요. (상록수 콘텐츠 지향)
- 인물 묘사: 한국인(Korean person) 기준.
- 형식: 
  - 문단: <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph -->
  - 제목: <!-- wp:heading {{"level":2}} --><h2>제목</h2><!-- /wp:heading -->
  - 버튼: <!-- wp:buttons {{"layout":{{"type":"flex","justifyContent":"center"}}}} --><div class="wp-block-buttons"><!-- wp:button {{"className":"is-style-fill"}} --><div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="URL">텍스트</a></div><!-- /wp:button --></div><!-- /wp:buttons -->
- 출력: 반드시 완결된 JSON으로 응답."""
    
    user_query = f"내부추천:\n{internal_ref_data}\n\n외부참조:\n{external_ref_data}\n\n키워드: {keyword}"
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "tools": [{"google_search": {}}], 
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 8192
        }
    }
    
    res = safe_api_call(url, payload, timeout=400)
    if res:
        try:
            raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
            json_str = raw_text.strip().replace('```json', '').replace('```', '')
            json_str = re.sub(r'\[\d+\]', '', json_str)
            return json.loads(json_str)
        except: pass
    return None

# ==========================================
# 6. 워드프레스 발행 로직
# ==========================================
def get_or_create_term(taxonomy, name, auth):
    endpoint = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/{taxonomy}"
    try:
        r = requests.get(f"{endpoint}?search={name}", auth=auth, timeout=10)
        if r.status_code == 200 and r.json():
            for t in r.json():
                if t['name'].lower() == name.lower(): return t['id']
        cr = requests.post(endpoint, auth=auth, json={"name": name}, timeout=10)
        if cr.status_code == 201: return cr.json()['id']
    except: pass
    return None

def post_article(data, mid):
    print("📢 워드프레스 발행 시도 중...", flush=True)
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    cat_id = get_or_create_term('categories', data.get('category', '생활정보'), auth)
    tag_ids = [get_or_create_term('tags', t, auth) for t in data.get('tags', []) if t]
    tag_ids = [tid for tid in tag_ids if tid]

    payload = {
        "title": data.get('title', '정보 안내'), 
        "content": data.get('content', ''), 
        "excerpt": data.get('excerpt', ''),
        "categories": [cat_id] if cat_id else [],
        "tags": tag_ids, 
        "featured_media": mid, 
        "status": "publish"
    }
    
    try:
        res = requests.post(url, auth=auth, json=payload, timeout=60)
        if res.status_code == 201:
            print(f"🚀 발행 성공: {res.json().get('link')}")
            return True
        else:
            print(f"❌ 워드프레스 발행 실패: {res.status_code}")
    except Exception as e:
        print(f"❌ 발행 중 예외 발생: {e}")
    return False

# ==========================================
# 7. 메인 실행부
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ API 키 누락"); return

    # 전역 변수 IS_TEST를 다시 한번 확인하여 출력
    # GitHub Actions의 환경 변수가 'true' 인지 정확히 판별합니다.
    if IS_TEST:
        print("🛠️ 테스트 모드 활성화됨: 랜덤 대기 시간을 건너뜁니다.", flush=True)
    else:
        print("🚀 상용 모드 활성화됨: 랜덤 대기 시간을 시작합니다.", flush=True)

    kst = timezone(timedelta(hours=9))
    current_date_str = datetime.now(kst).strftime("%Y년 %m월 %d일")

    if not IS_TEST:
        delay = random.randint(0, 3300)
        print(f"⏳ {delay // 60}분 랜덤 대기...", flush=True)
        time.sleep(delay)

    engine = VersatileKeywordEngine(GEMINI_API_KEY)
    target = engine.generate_target(current_date_str)
    
    json_links = load_external_links_from_json()
    rss_links = get_rss_links(RSS_URLS)
    combined_external_links = json_links + rss_links
    recent_posts = get_recent_posts()
    
    data = generate_article(target, recent_posts, combined_external_links, current_date_str)
    if not data: 
        print("❌ 콘텐츠 생성 단계에서 실패했습니다.")
        return
    
    mid = None
    if data.get('image_prompt'):
        img_data = generate_image_process(data['image_prompt'])
        if img_data: mid = upload_to_wp_media(img_data)
    
    post_article(data, mid)

if __name__ == "__main__":
    main()
