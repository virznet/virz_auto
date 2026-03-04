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

# [2026-03-04 기준] 테스트 모드 활성화 (True: 즉시 실행 / False: 랜덤 대기 적용)
IS_TEST = False

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
            elif res.status_code == 404:
                print(f"⚠️ API 오류 (HTTP 404): 엔드포인트 또는 모델명이 잘못되었습니다. URL: {url}")
                return None
            elif res.status_code == 429:
                print(f"⚠️ 할당량 초과(429). {delays[i]}초 후 다시 시도...")
                time.sleep(delays[i])
            else:
                print(f"⚠️ API 오류 (HTTP {res.status_code}). 응답: {res.text[:200]}")
                time.sleep(delays[i])
        except Exception as e:
            print(f"⚠️ 요청 중 예외 발생: {e}. {delays[i]}초 후 다시 시도...")
            time.sleep(delays[i])
    return None

# ==========================================
# 3. 다분야 롱테일 키워드 생성 엔진
# ==========================================
class VersatileKeywordEngine:
    def __init__(self, api_key):
        self.api_key = api_key
        # [수정] 2026년 기준 최신 안정화 텍스트 모델 적용
        self.model = "gemini-flash-latest" 
        self.categories = {
            "건강정보": ["만성 질환 예방", "필수 영양제 가이드", "심리 상담", "재활 운동", "수면 장애 극복"],
            "복지정보": ["정부 지원금 신청", "시니어 복지", "청년 주거 지원", "육아 휴직 활용", "아동 수당 활용", "장애인 고용 지원"],
            "생활정보": ["세무 상식", "법률 상식", "친환경 살림", "저축 방법", "요리 비법"]
        }

    def generate_target(self, current_date):
        selected_cat = random.choice(list(self.categories.keys()))
        seed_topic = random.choice(self.categories[selected_cat])
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        prompt = f"당신은 SEO 전문가입니다. '{selected_cat}' 분야의 '{seed_topic}'와 관련된 롱테일 키워드 1개를 JSON으로 생성하세요. 결과는 반드시 {{'keyword': '...', 'category': '...'}} 형식이어야 합니다. 연도 정보는 제외하세요."

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        
        res = safe_api_call(url, payload)
        if res:
            try:
                text = res.json()['candidates'][0]['content']['parts'][0]['text']
                data = json.loads(text)
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                return data
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
                items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)
                for item in items[:3]:
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
    """최신 Imagen 4.0 모델을 사용하여 고품질 이미지를 생성하고 JPG 70% 품질로 최적화"""
    print(f"🎨 이미지 생성 시도 중... (프롬프트: {prompt[:50]}...)", flush=True)
    
    # 2026년 기준 최신 이미지 생성 모델 및 엔드포인트 적용
    model_id = "imagen-4.0-generate-001"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:predict?key={GEMINI_API_KEY}"
    
    final_prompt = f"Korean person, {prompt}. Professional photography, clean composition, high resolution. NO TEXT."
    
    # Imagen 4.0 전용 페이로드 구조
    payload = {
        "instances": [{"prompt": final_prompt}], 
        "parameters": {"sampleCount": 1}
    }
    
    res = safe_api_call(url, payload, timeout=150)
    if res:
        try:
            result = res.json()
            if 'predictions' in result and len(result['predictions']) > 0:
                b64_data = result['predictions'][0]['bytesBase64Encoded']
                img = Image.open(io.BytesIO(base64.b64decode(b64_data)))
                if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                output_buffer = io.BytesIO()
                img.save(output_buffer, format="JPEG", quality=70, optimize=True)
                print("✅ 이미지 변환 및 최적화 완료 (JPG 70%)")
                return output_buffer.getvalue()
        except Exception as e:
            print(f"⚠️ 이미지 데이터 처리 실패: {e}")
    return None

def upload_to_wp_media(img_data):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=auto_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201: 
            print(f"✅ 미디어 업로드 성공 (ID: {res.json()['id']})")
            return res.json()['id']
    except: pass
    return None

# ==========================================
# 5. 고도화된 콘텐츠 생성 (Gutenberg 최적화)
# ==========================================
def generate_article(target, internal_posts, combined_external_links):
    if isinstance(target, list) and len(target) > 0:
        target = target[0]
        
    keyword = target.get('keyword', '상세 가이드')
    category = target.get('category', '생활정보')
    
    print(f"🤖 [{category}] 분야 콘텐츠 생성 중: {keyword}", flush=True)
    
    # [수정] 텍스트 모델 최신 버전으로 강제 지정
    model_id = "gemini-flash-latest"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    selected_int = random.sample(internal_posts, min(len(internal_posts), 2)) if internal_posts else []
    selected_ext = random.sample(combined_external_links, min(len(combined_external_links), 3))

    system_prompt = f"""당신은 {category} 전문 에디터입니다. 구텐베르크 블록 에디터 방식에 최적화된 심층 글을 작성하세요.
- 분량: 2,500자 이상.
- 날짜 제외: 2026년 등 연도, 월, 일 정보를 제목과 본문에 포함하지 마세요. (상록수 콘텐츠 지향)
- 인물: 한국인(Korean person) 기준.
- 필수 포함 JSON 키: "title", "content", "image_prompt", "category", "tags"
- 형식: 
  - 문단: <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph -->
  - 제목: <!-- wp:heading {{"level":2}} --><h2>제목</h2><!-- /wp:heading -->
- 출력: 반드시 유효한 JSON으로만 응답하세요."""
    
    user_query = f"내부링크: {selected_int}\n외부링크: {selected_ext}\n키워드: {keyword}"
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "tools": [{"google_search": {}}], 
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 8192}
    }
    
    res = safe_api_call(url, payload, timeout=400)
    if res:
        try:
            raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(raw_text.strip().replace('```json', '').replace('```', ''))
            
            if isinstance(data, list) and len(data) > 0:
                data = data[0]

            if not data.get('title') or not data.get('content'):
                print("⚠️ AI 응답에 필수 필드(title/content)가 누락되었습니다.")
                return None
            return data
        except Exception as e:
            print(f"⚠️ 콘텐츠 JSON 파싱 실패: {e}")
            print(f"응답 텍스트 일부: {raw_text[:200]}")
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
    if not data or 'title' not in data: return False
    print(f"📢 워드프레스 발행 시도 중: {data['title']}", flush=True)
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    cat_id = get_or_create_term('categories', data.get('category', '생활정보'), auth)
    tag_ids = [get_or_create_term('tags', t, auth) for t in data.get('tags', []) if t]
    tag_ids = [tid for tid in tag_ids if tid]

    payload = {
        "title": data['title'], 
        "content": data['content'], 
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
            print(f"❌ 발행 실패: {res.status_code} - {res.text[:200]}")
    except Exception as e:
        print(f"❌ 발행 중 예외 발생: {e}")
    return False

# ==========================================
# 7. 메인 실행부
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ API 키 누락"); return

    if IS_TEST:
        print("🛠️ 테스트 모드: 즉시 실행", flush=True)
    else:
        delay = random.randint(0, 3300)
        print(f"⏳ {delay // 60}분 랜덤 대기...", flush=True)
        time.sleep(delay)

    # 2026년 3월 4일 시간 설정
    kst = timezone(timedelta(hours=9))
    current_date_str = datetime.now(kst).strftime("%Y년 %m월 %d일")

    # 키워드 생성
    engine = VersatileKeywordEngine(GEMINI_API_KEY)
    target = engine.generate_target(current_date_str)
    
    if not target:
        print("❌ 키워드 생성 실패")
        return

    # 외부 리소스 수집
    combined_external_links = load_external_links_from_json() + get_rss_links(RSS_URLS)
    recent_posts = get_recent_posts()
    
    # 1. 콘텐츠 생성 및 검증
    data = generate_article(target, recent_posts, combined_external_links)
    if not data:
        print("❌ 유효한 콘텐츠가 생성되지 않아 프로세스를 중단합니다.")
        return
    
    # 2. 이미지 생성
    mid = None
    image_prompt = data.get('image_prompt')
    if image_prompt:
        img_data = generate_image_process(image_prompt)
        if img_data: 
            mid = upload_to_wp_media(img_data)
    else:
        print("⚠️ 이미지 프롬프트가 없어 이미지 생성을 건너뜁니다.")
    
    # 3. 최종 발행
    post_article(data, mid)

if __name__ == "__main__":
    main()
