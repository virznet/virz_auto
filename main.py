import os
import random
import time
import requests
import json
import base64
import re
import io
import sys
import traceback
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

# 외부 링크 수집용 RSS 리스트
RSS_URLS = [
    "https://virz.net/feed",
    "https://121913.tistory.com/rss",
    "https://exciting.tistory.com/rss",
    "https://sleepyourmoney.net/feed",
    "https://rss.blog.naver.com/moviepotal.xml"
]

# 테스트 모드 설정 (True일 경우 대기 시간 없이 즉시 실행)
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# 공통 헤더 (보안 방화벽 우회 시도용)
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
}

# ==========================================
# 2. 다분야 롱테일 키워드 생성 엔진
# ==========================================
class VersatileKeywordEngine:
    def __init__(self, api_key):
        self.api_key = api_key
        self.model = "gemini-1.5-flash" # 표준 모델명으로 교정
        self.categories = {
            "건강정보": ["만성 질환 예방", "필수 영양제 가이드", "심리 상담", "재활 운동", "수면 장애 극복"],
            "복지정보": ["정부 지원금 신청", "시니어 복지", "청년 주거 지원", "육아 휴직 활용", "장애인 고용 지원"],
            "생활정보": ["세무 상식", "법률 상식", "친환경 살림", "저축 방법", "요리 비법"]
        }

    def generate_target(self, current_date):
        selected_cat = random.choice(list(self.categories.keys()))
        seed_topic = random.choice(self.categories[selected_cat])
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        prompt = f"당신은 SEO 전문가입니다. {current_date} 기준 {selected_cat} 분야의 {seed_topic}와 관련된 검색 의도가 명확한 롱테일 키워드 1개를 JSON으로 생성하세요. 결과에 연도나 날짜 정보는 절대 포함하지 마세요."

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        try:
            res = requests.post(url, json=payload, timeout=30)
            if res.status_code == 200:
                result_json = res.json()
                text = result_json.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                if text:
                    return json.loads(text)
        except Exception as e:
            print(f"⚠️ 키워드 생성 실패: {e}")
        
        return {"keyword": f"{seed_topic} 가이드", "category": selected_cat}

# ==========================================
# 3. 데이터 수집 및 이미지 처리
# ==========================================
def get_rss_links(rss_urls):
    rss_links = []
    print(f"📡 RSS 피드에서 외부 링크 수집 중...", flush=True)
    for url in rss_urls:
        try:
            response = requests.get(url, timeout=15, headers=COMMON_HEADERS)
            if response.status_code == 200:
                content = response.text
                items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)
                for item in items[:5]:
                    title_match = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
                    link_match = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
                    if title_match and link_match:
                        title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title_match.group(1)).strip()
                        link = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', link_match.group(1)).strip()
                        rss_links.append({"title": title, "url": link})
        except Exception:
            continue
    return rss_links

def load_external_links_from_json():
    file_path = "links.json"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return [{"title": "virz.net", "url": "https://virz.net"}]

def get_recent_posts():
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", headers=COMMON_HEADERS, timeout=15)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except:
        return []

def generate_image_process(prompt):
    print(f"🎨 이미지 생성 중...", flush=True)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    final_prompt = f"Korean person, {prompt}. Professional photography, clean composition, high detail. NO TEXT."
    payload = {"instances": [{"prompt": final_prompt}], "parameters": {"sampleCount": 1}}
    try:
        res = requests.post(url, json=payload, timeout=150)
        if res.status_code == 200:
            predictions = res.json().get('predictions', [])
            if predictions:
                b64_data = predictions[0].get('bytesBase64Encoded')
                img_bytes = base64.b64decode(b64_data)
                img = Image.open(io.BytesIO(img_bytes))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70, optimize=True)
                return buf.getvalue()
    except Exception as e:
        print(f"⚠️ 이미지 생성 또는 변환 실패: {e}")
    return None

def upload_to_wp_media(img_data):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {**COMMON_HEADERS, "Content-Disposition": f"attachment; filename=auto_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201:
            return res.json().get('id')
    except Exception:
        pass
    return None

# ==========================================
# 4. 콘텐츠 생성
# ==========================================
def generate_article(target, internal_posts, combined_external_links, current_date):
    keyword = target.get('keyword', '알 수 없는 주제')
    category = target.get('category', '생활정보')
    print(f"🤖 [{category}] 콘텐츠 생성 중: {keyword}", flush=True)
    
    model_id = "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    selected_int = random.sample(internal_posts, min(len(internal_posts), 2)) if internal_posts else []
    selected_ext = random.sample(combined_external_links, min(len(combined_external_links), 3)) if combined_external_links else []

    system_prompt = f"""당신은 {category} 전문 에디터입니다. 2,500~3,000자 분량의 구텐베르크 블록 기반 포스트를 작성하세요. 
    1. 제목과 본문에 연도/날짜 정보 절대 포함 금지.
    2. 인물 묘사 시 한국인(Korean person) 모델 기준.
    3. 구텐베르크 블록 형식(<!-- wp:paragraph --> 등) 엄격 준수.
    4. 결과를 반드시 유효한 JSON으로 출력."""
    
    user_query = f"대상 키워드: {keyword}\n\n추천 내부 링크 데이터: {selected_int}\n\n추천 외부 링크 데이터: {selected_ext}"
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "tools": [{"google_search": {}}], 
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 8192}
    }
    
    try:
        res = requests.post(url, json=payload, timeout=300)
        if res.status_code == 200:
            result_json = res.json()
            raw_text = result_json.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            # 인용 마커 및 불필요한 마크다운 기호 정제
            clean_text = re.sub(r'\[\d+\]', '', raw_text)
            clean_text = clean_text.strip().replace('```json', '').replace('```', '')
            return json.loads(clean_text)
        else:
            print(f"⚠️ 콘텐츠 생성 API 오류: HTTP {res.status_code}")
    except Exception as e:
        print(f"⚠️ 콘텐츠 생성 실패: {e}")
    return None

# ==========================================
# 5. 워드프레스 발행
# ==========================================
def get_or_create_term(taxonomy, name, auth):
    endpoint = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/{taxonomy}"
    try:
        r = requests.get(f"{endpoint}?search={name}", auth=auth, headers=COMMON_HEADERS, timeout=15)
        if r.status_code == 200 and r.json():
            for t in r.json():
                if t['name'].lower() == name.lower():
                    return t['id']
        cr = requests.post(endpoint, auth=auth, headers=COMMON_HEADERS, json={"name": name}, timeout=15)
        if cr.status_code == 201:
            return cr.json().get('id')
    except:
        pass
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
        res = requests.post(url, auth=auth, headers=COMMON_HEADERS, json=payload, timeout=60)
        if res.status_code == 201:
            print(f"🚀 발행 성공: {res.json().get('link')}")
            return True
        else:
            print(f"❌ 발행 실패 (HTTP {res.status_code})")
            if "<script" in res.text or "slowAES" in res.text:
                print("⚠️ 원인: 카페24 '스팸 SHIELD' 차단. '사용안함'으로 변경이 필요합니다.")
            else:
                print(f"서버 응답 요약: {res.text[:200]}")
    except Exception as e:
        print(f"❌ 발행 중 예외 발생: {e}")
    return False

# ==========================================
# 6. 메인 실행 및 에러 추적
# ==========================================
def main():
    if not GEMINI_API_KEY:
        print("❌ 오류: GEMINI_API_KEY가 설정되지 않았습니다.")
        sys.exit(1)

    kst = timezone(timedelta(hours=9))
    current_date_str = datetime.now(kst).strftime("%Y년 %m월 %d일")

    if not IS_TEST:
        delay = random.randint(0, 3300)
        print(f"⏳ {delay // 60}분 랜덤 대기...")
        time.sleep(delay)

    engine = VersatileKeywordEngine(GEMINI_API_KEY)
    target = engine.generate_target(current_date_str)
    
    json_links = load_external_links_from_json()
    rss_links = get_rss_links(RSS_URLS)
    combined_external_links = json_links + rss_links
    
    recent_posts = get_recent_posts()
    
    data = generate_article(target, recent_posts, combined_external_links, current_date_str)
    
    if data:
        mid = None
        if data.get('image_prompt'):
            img_data = generate_image_process(data['image_prompt'])
            if img_data:
                mid = upload_to_wp_media(img_data)
        post_article(data, mid)
    else:
        print("❌ 콘텐츠 생성 실패로 인해 프로세스를 종료합니다.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n" + "="*50)
        print("🚨 치명적 오류 발생 (Traceback):")
        traceback.print_exc()
        print("="*50)
        sys.exit(1)
