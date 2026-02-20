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

# 외부 링크 수집용 RSS 리스트
RSS_URLS = [
    "https://virz.net/feed",
    "https://121913.tistory.com/rss",
    "https://exciting.tistory.com/rss",
    "https://sleepyourmoney.net/feed"
]

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
        """현재 시점을 인지하되, 제목과 키워드에서 연도를 배제함"""
        selected_cat = random.choice(list(self.categories.keys()))
        seed_topic = random.choice(self.categories[selected_cat])
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        
        prompt = f"""당신은 SEO 전문가입니다. 오늘 날짜는 {current_date}입니다.
분야 '{selected_cat}'의 주제 '{seed_topic}'와 관련하여 현재 시점에 가장 유효한 구체적인 '롱테일 키워드' 1개를 생성하세요. 

[지침]
1. 검색 의도가 명확하고 정보가 풍부한 주제를 선정하세요.
2. 생성되는 키워드에 연도(2026년 등)나 특정 날짜 정보를 절대로 포함하지 마세요.
3. 결과는 반드시 JSON 형식으로만 응답하세요.
{{
  "keyword": "연도 정보가 없는 구체적인 롱테일 키워드 문구",
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
# 3. 워드프레스 및 이미지 처리 & 링크 수집
# ==========================================
def get_rss_links(rss_urls):
    """지정된 RSS 피드 주소들로부터 최신 글의 제목과 링크를 수집 (정규표현식 보조 파싱)"""
    rss_links = []
    print(f"📡 RSS 피드에서 외부 링크 수집 중...", flush=True)
    for url in rss_urls:
        try:
            response = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code == 200:
                content = response.text
                
                # ElementTree 파싱 시도
                try:
                    # XML 선언 뒤의 부적절한 문자 제거 시도
                    content_clean = re.sub(r'^[^\<]*', '', content) 
                    root = ET.fromstring(content_clean.encode('utf-8'))
                    
                    for item in root.findall(".//item")[:5]:
                        title = item.find("title").text if item.find("title") is not None else ""
                        link = item.find("link").text if item.find("link") is not None else ""
                        if title and link:
                            rss_links.append({"title": title.strip(), "url": link.strip()})
                except ET.ParseError:
                    # ElementTree 실패 시 정규표현식으로 제목과 링크 추출 (강제 복구)
                    items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)
                    for item in items[:5]:
                        title_match = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
                        link_match = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
                        if title_match and link_match:
                            title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title_match.group(1)).strip()
                            link = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', link_match.group(1)).strip()
                            rss_links.append({"title": title, "url": link})
        except Exception as e:
            print(f"⚠️ RSS 수집 실패 ({url}): {e}", flush=True)
    return rss_links

def load_external_links_from_json():
    file_path = "links.json"
    default_links = [{"title": "virz.net", "url": "https://virz.net"}]
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return default_links
    return default_links

def get_recent_posts():
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except: return []

def generate_image_process(prompt):
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
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=auto_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201: return res.json()['id']
    except: pass
    return None

# ==========================================
# 4. 고도화된 콘텐츠 생성 (안정성 강화)
# ==========================================
def generate_article(target, internal_posts, combined_external_links, current_date):
    """Gemini를 사용하여 구텐베르크 블록 기반의 심층 포스트 생성 (토큰 상향 및 안정성 강화)"""
    keyword = target['keyword']
    category = target['category']
    
    print(f"🤖 [{category}] 분야 콘텐츠 생성 중: {keyword}")
    
    model_id = "gemini-flash-latest"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    selected_int = random.sample(internal_posts, min(len(internal_posts), 2)) if internal_posts else []
    internal_ref_data = "\n".join([f"제목: {p['title']} | 링크: {p['link']}" for p in selected_int])
    
    selected_ext = random.sample(combined_external_links, min(len(combined_external_links), 3))
    external_ref_data = "\n".join([f"제목: {l['title']} | 링크: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 분야의 전문 에디터입니다. 
키워드 '{keyword}'에 대해 워드프레스 구텐베르크 블록 에디터 방식에 최적화된 블로그 글을 작성하세요.

[필수 요구사항 - 분량 및 토큰]
- 목표 분량: 공백 제외 2,500자 ~ 3,000자 내외.
- **매우 중요**: 글이 중간에 끊기지 않도록 끝까지 완결된 JSON 구조를 출력하세요. 

[구텐베르크 블록 형식]
- 문단: <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph -->
- 제목(H2): <!-- wp:heading {{"level":2}} --><h2>제목</h2><!-- /wp:heading -->
- 리스트: <!-- wp:list --><ul><li>항목</li></ul><!-- /wp:list -->
- 버튼: <!-- wp:buttons {{"layout":{{"type":"flex","justifyContent":"center"}}}} -->
     <div class="wp-block-buttons">
       <!-- wp:button {{"className":"is-style-fill"}} -->
       <div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="URL">텍스트</a></div>
       <!-- /wp:button -->
     </div>
     <!-- /wp:buttons -->

[가독성]
- 한 문단은 2~3문장 이내로 짧게 구성하세요.
- 핵심 키워드는 <strong> 태그로 볼드 처리하세요.

[기타]
- 연도 및 날짜를 포함하지 마세요.
- 반드시 유효한 JSON 형식으로 응답하세요. 본문 내 큰따옴표는 반드시 백슬래시로 이스케이프(\") 하세요.
"""
    
    user_query = f"""
[내 블로그 추천글 리스트]
{internal_ref_data}

[외부 참조 링크 리스트]
{external_ref_data}

대상 키워드: {keyword}
카테고리: {category}
"""
    
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
        "tools": [{"google_search": {}}], 
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
            "maxOutputTokens": 8192 # [수정] 장문 생성을 위해 토큰 제한을 대폭 상향
        }
    }
    
    for i in range(5):
        try:
            res = requests.post(url, json=payload, timeout=300)
            if res.status_code == 200:
                raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
                
                # [안정성] JSON 파싱 전 불필요한 마크다운 코드 블록 기호 제거 및 정제
                json_str = raw_text.strip()
                if json_str.startswith("```"):
                    json_str = re.sub(r'^`{3}(?:json)?\s*', '', json_str)
                    json_str = re.sub(r'\s*`{3}$', '', json_str)
                
                # 구글 검색 인용 마커 제거
                json_str = re.sub(r'\[\d+\]', '', json_str)
                
                return json.loads(json_str)
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
        res = requests.post(url, auth=auth, json=payload, timeout=60)
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

    kst = timezone(timedelta(hours=9))
    current_date_str = datetime.now(kst).strftime("%Y년 %m월 %d일")

    if not IS_TEST:
        delay = random.randint(0, 3300)
        print(f"⏳ {delay // 60}분 랜덤 대기...")
        time.sleep(delay)

    engine = VersatileKeywordEngine(GEMINI_API_KEY)
    target = engine.generate_target(current_date_str)
    
    # 1. 고정 외부 링크 + 동적 RSS 링크 수집
    json_links = load_external_links_from_json()
    rss_links = get_rss_links(RSS_URLS)
    combined_external_links = json_links + rss_links
    
    # 2. 내부 최근 포스트 로드
    recent_posts = get_recent_posts()
    
    # 3. AI 글 생성
    data = generate_article(target, recent_posts, combined_external_links, current_date_str)
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
