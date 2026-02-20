import os
import random
import time
import requests
import json
import base64
import re
import io
import sys
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

# 테스트 모드 설정 (true일 경우 대기 시간 없이 즉시 실행)
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# ==========================================
# 2. 다분야 롱테일 키워드 생성 엔진
# ==========================================
class VersatileKeywordEngine:
    """건강, 복지, 생활정보 분야의 롱테일 키워드를 무작위로 생성하는 엔진"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.model = "gemini-flash-latest"
        self.categories = {
            "건강정보": [
                "만성 질환 예방 및 식단 관리", "연령대별 필수 영양제 가이드", 
                "심리 상담 및 스트레스 해소법", "집에서 하는 재활 운동 및 스트레칭",
                "수면 장애 극복 및 숙면 팁"
            ],
            "복지정보": [
                "정부 지원금 및 바우처 신청 자격", "노인 및 시니어 복지 혜택 정리",
                "청년 및 신혼부부 주거 지원 정책", "육아 휴직 및 아동 수당 활용법",
                "장애인 편의 시설 및 고용 지원"
            ],
            "생활정보": [
                "절세를 위한 세무 상식 및 연말정산", "일상 속 법률 상식 및 계약 주의사항",
                "친환경 살림 팁 및 청소 노하우", "가계부 정리 및 스마트한 저축 방법",
                "제철 식재료 보관 및 요리 비법"
            ]
        }

    def generate_target(self, current_date):
        """현재 시점을 인지하되, 불필요한 연도 언급을 지양하는 키워드 생성"""
        selected_cat = random.choice(list(self.categories.keys()))
        seed_topic = random.choice(self.categories[selected_cat])
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        
        prompt = f"""당신은 SEO 전문가입니다. 오늘 날짜는 {current_date}입니다.
분야 '{selected_cat}'의 주제 '{seed_topic}'와 관련하여 현재 시점에 가장 유효한 구체적인 '롱테일 키워드' 1개를 생성하세요. 

[지침]
1. 검색 의도가 명확하고 정보가 풍부한 주제를 선정하세요.
2. '2026년'과 같은 연도는 특정 정책이나 매년 바뀌는 혜택처럼 연도 표기가 필수적인 경우에만 포함하세요.
3. 일반적인 건강 상식이나 생활 팁에는 연도를 붙이지 마세요.
4. 결과는 반드시 JSON 형식으로만 응답하세요.
{{
  "keyword": "구체적인 롱테일 키워드 문구",
  "category": "{selected_cat}"
}}"""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        try:
            res = requests.post(url, json=payload, timeout=30)
            if res.status_code == 200:
                text = res.json()['candidates'][0]['content']['parts'][0]['text']
                return json.loads(text)
        except Exception as e:
            print(f"⚠️ 키워드 생성 실패: {e}")
        
        return {"keyword": f"{seed_topic} 상세 가이드", "category": selected_cat}

# ==========================================
# 3. 워드프레스 및 이미지 처리
# ==========================================
def load_external_links():
    """links.json 파일에서 외부 링크 목록을 로드"""
    file_path = "links.json"
    default_links = [{"title": "virz.net", "url": "https://virz.net"}]
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return default_links
    return default_links

def get_recent_posts():
    """워드프레스에서 최근 포스트 목록을 가져와 내부 링크로 활용"""
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except: return []

def generate_image_process(prompt):
    """Imagen 모델을 사용하여 포스팅용 이미지를 생성"""
    print(f"🎨 이미지 생성 중... (주제: {prompt[:30]}...)")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    final_prompt = f"High-quality commercial photography for: {prompt}. Professional lighting, clean composition. NO TEXT."
    payload = {"instances": [{"prompt": final_prompt}], "parameters": {"sampleCount": 1}}
    try:
        response = requests.post(url, json=payload, timeout=150)
        if response.status_code == 200:
            result = response.json()
            if 'predictions' in result:
                b64_data = result['predictions'][0]['bytesBase64Encoded']
                return base64.b64decode(b64_data)
    except: pass
    return None

def upload_to_wp_media(img_data):
    """생성된 이미지를 워드프레스 미디어 라이브러리에 업로드"""
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=auto_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201: return res.json()['id']
    except: pass
    return None

# ==========================================
# 4. 고도화된 콘텐츠 생성 (안정성 및 메모리 최적화)
# ==========================================
def generate_article(target, internal_posts, user_links, current_date):
    """Gemini를 사용하여 SEO 최적화된 블로그 포스트 생성"""
    keyword = target['keyword']
    category = target['category']
    
    print(f"🤖 [{category}] 분야 콘텐츠 생성 중: {keyword}")
    
    model_id = "gemini-flash-latest"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    selected_int = random.sample(internal_posts, min(len(internal_posts), 2)) if internal_posts else []
    internal_ref = "내 블로그 추천글:\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in selected_int])
    
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "외부 링크:\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    # 서버 메모리 부하 방지를 위해 블록 구조 단순화 및 분량 조절
    system_prompt = f"""당신은 {category} 분야의 전문 에디터입니다. 
오늘 날짜 {current_date}를 기준으로 정확한 정보를 바탕으로 키워드 '{keyword}'에 대한 블로그 글을 작성하세요.

[시의성 가이드]
1. 오늘 날짜를 기준으로 가장 최신의 정보를 제공하되, 연도 표기는 필수적인 경우에만 사용하세요.
2. 구글 검색 도구를 통해 현재 시점의 유효한 데이터를 확인하고 반영하세요.

[구텐베르크 블록 최적화 가이드]
1. 서버 메모리 부하 방지를 위해 복잡한 중첩 블록은 지양하세요.
2. 모든 텍스트는 반드시 <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph --> 형식을 유지하세요.
3. 소제목은 <!-- wp:heading {{"level":2}} --><h2>소제목</h2><!-- /wp:heading --> 형식을 사용하세요.
4. 블록 주석이 깨지지 않도록 여는 주석과 닫는 주석을 엄격히 짝지으세요.

[출력 지침]
- 전체 분량은 약 1500~2000자 정도로 전문성을 유지하면서도 핵심 위주로 작성하세요.
- 인물은 한국인(Korean person) 모델로 묘사하세요.
- 반드시 유효한 JSON 형식으로 응답하세요. 본문 내 큰따옴표는 이스케이프 하세요.
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n카테고리: {category}"
    
    # 응답 스키마 강제 적용
    response_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "category": {"type": "string"},
            "content": {"type": "string"},
            "excerpt": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "image_prompt": {"type": "string"}
        },
        "required": ["title", "category", "content", "excerpt", "tags", "image_prompt"]
    }

    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "tools": [{"google_search": {}}], # 실시간 검색 활용
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
            "maxOutputTokens": 4096 # 출력량 제한 (서버 500 에러 방지용)
        }
    }
    
    for i in range(5):
        try:
            res = requests.post(url, json=payload, timeout=240)
            if res.status_code == 200:
                raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                # 검색 인용 마커 제거
                clean_text = re.sub(r'\[\d+\]', '', raw_text)
                return json.loads(clean_text)
            else:
                print(f"⚠️ API 오류 (HTTP {res.status_code}): {res.text}")
            time.sleep(2**i)
        except Exception as e:
            print(f"⚠️ 생성 실패 (시도 {i+1}/5): {e}")
            time.sleep(2**i)
    return None

# ==========================================
# 5. 워드프레스 발행 로직
# ==========================================
def get_or_create_term(taxonomy, name, auth):
    """카테고리 또는 태그가 없으면 생성하고 ID를 반환"""
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
    """최종 생성된 데이터를 워드프레스에 포스팅"""
    print("📢 워드프레스 발행 시도 중...")
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
        res = requests.post(url, auth=auth, json=payload, timeout=40)
        if res.status_code == 201:
            print(f"🚀 발행 성공: {res.json().get('link')}")
            return True
        else:
            print(f"❌ 발행 실패 (HTTP {res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ 발행 중 예외 발생: {e}")
    return False

# ==========================================
# 6. 메인 실행부
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ API 키 누락"); return

    # 한국 시간 기준 날짜 설정
    kst = timezone(timedelta(hours=9))
    current_date_str = datetime.now(kst).strftime("%Y년 %m월 %d일")

    # 랜덤 대기 (서버 부하 및 자동화 탐지 방지)
    if not IS_TEST:
        delay = random.randint(0, 3300)
        print(f"⏳ {delay // 60}분 랜덤 대기...")
        time.sleep(delay)

    # 1. 분야 및 롱테일 키워드 생성
    engine = VersatileKeywordEngine(GEMINI_API_KEY)
    target = engine.generate_target(current_date_str)
    
    # 2. 관련 리소스 로드
    user_links = load_external_links()
    recent_posts = get_recent_posts()
    
    # 3. AI 글 생성
    data = generate_article(target, recent_posts, user_links, current_date_str)
    if not data: 
        print("❌ 콘텐츠 생성 단계에서 실패했습니다.")
        return
    
    # 4. 이미지 생성 및 업로드
    mid = None
    if data.get('image_prompt'):
        img_data = generate_image_process(data['image_prompt'])
        if img_data: mid = upload_to_wp_media(img_data)
    
    # 5. 워드프레스 최종 발행
    post_article(data, mid)

if __name__ == "__main__":
    main()
