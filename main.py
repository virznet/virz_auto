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
WP_BASE_URL = "https://virz.net" 

# 테스트 모드: True일 경우 1개만 즉시 발행하고 종료
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# ==========================================
# 2. 데이터 로드 및 수집 로직
# ==========================================
def load_external_links():
    """links.json 파일에서 사용자 정의 외부 링크 목록을 불러옵니다."""
    file_path = "links.json"
    default_links = [{"title": "virz.net", "url": "https://virz.net"}]
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if data else default_links
        except Exception as e:
            print(f"⚠️ links.json 로드 실패: {e}", flush=True)
            return default_links
    return default_links

class NaverScraper:
    """네이버 뉴스 및 블로그에서 최신 키워드 수집"""
    def __init__(self):
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"}

    def get_news_ranking(self, section_id):
        try:
            res = requests.get(f"https://news.naver.com/main/ranking/popularDay.naver?sectionId={section_id}", headers=self.headers, timeout=15)
            res.encoding = res.apparent_encoding if res.apparent_encoding else 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            titles = []
            for t in soup.select(".rankingnews_list .list_title"):
                clean_title = t.text.strip()
                if clean_title:
                    titles.append(clean_title)
            return titles[:10]
        except Exception as e:
            print(f"뉴스 스크래핑 오류: {e}", flush=True)
            return []

    def get_blog_hot_topics(self):
        try:
            res = requests.get("https://section.blog.naver.com/HotTopicList.naver", headers=self.headers, timeout=15)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            return [t.text.strip() for t in soup.select(".list_hottopic .desc")[:10]]
        except Exception as e:
            print(f"블로그 핫토픽 스크래핑 오류: {e}", flush=True)
            return []

# ==========================================
# 3. 워드프레스 & 이미지 최적화 (JPG 70%)
# ==========================================
def get_recent_posts():
    """내부 링크 활용을 위해 워드프레스에서 최근 글 목록을 가져옵니다."""
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except Exception as e:
        print(f"최근 포스트 로드 오류: {e}", flush=True)
    return []

def generate_image_process(prompt):
    """Imagen 4.0으로 이미지 생성 후 JPG 70% 압축 처리"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    
    # 글자가 없는 깨끗한 썸네일을 위한 영문 프롬프트 보강
    final_prompt = f"Professional photography for: {prompt}. High resolution, 8k, cinematic lighting. Strictly NO TEXT, NO LETTERS, NO WORDS, NO FONTS."
    
    payload = {
        "instances": [{"prompt": final_prompt}],
        "parameters": {"sampleCount": 1}
    }
    
    try:
        response = requests.post(url, json=payload, timeout=150)
        if response.status_code == 200:
            result = response.json()
            b64_data = result['predictions'][0]['bytesBase64Encoded']
            img_data = base64.b64decode(b64_data)
            
            # Pillow를 사용한 JPG 변환 및 70% 압축
            img = Image.open(io.BytesIO(img_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            out = io.BytesIO()
            img.save(out, format='JPEG', quality=70, optimize=True)
            return out.getvalue()
        else:
            print(f"이미지 생성 API 오류: {response.status_code}", flush=True)
    except Exception as e:
        print(f"이미지 생성 중 예외 발생: {e}", flush=True)
    return None

def upload_to_wp_media(img_data):
    """압축된 이미지를 워드프레스 미디어 라이브러리에 업로드합니다."""
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {
        "Content-Disposition": f"attachment; filename=feat_{int(time.time())}.jpg",
        "Content-Type": "image/jpeg"
    }
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201:
            return res.json()['id']
    except Exception as e:
        print(f"미디어 업로드 실패: {e}", flush=True)
    return None

# ==========================================
# 4. 스마트 콘텐츠 생성 (지능형 링크 전략)
# ==========================================
def generate_article(keyword, category, internal_posts, user_links):
    """Gemini 2.5 Flash를 사용하여 SEO 최적화된 콘텐츠를 생성합니다."""
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    # 내부 및 사용자 정의 링크 데이터 준비
    internal_ref = "내 블로그 추천글 목록:\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in internal_posts]) if internal_posts else ""
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "본문에 포함할 외부 링크 목록:\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 3,000자 이상의 매우 상세한 블로그 글을 작성하세요.

[SEO 링크 배치 가이드]
1. 내부 링크: 제공된 내 블로그 추천글 중 하나를 본문의 첫 번째 H2 섹션 이후에 자연스럽게 삽입하세요.
2. 사용자 외부 링크: 제공된 외부 링크 2개를 본문 중간중간(H2~H3 섹션 사이)에 분산 배치하세요. (텍스트 링크와 버튼 블록 혼용)
3. AI 권위 링크: 주제를 뒷받침할 공신력 있는 외부 출처(뉴스, 백과사전 등)를 AI가 직접 하나 더 찾아 본문 하단에 추가하세요.

[필수 규칙]
- 응답은 반드시 유효한 JSON 형식이어야 합니다.
- JSON 키: 'title', 'content', 'excerpt', 'tags', 'image_prompt'.
- 본문 내용은 워드프레스 구텐베르크 블록(HTML 주석 형식)을 사용해야 합니다.
- 중요: 텍스트 내의 모든 이중 따옴표(")는 백슬래시(\")를 사용해 반드시 이스케이프 처리하세요.
- 인사말, 날짜 언급 없이 바로 본론으로 시작하세요.
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n위 정보를 바탕으로 완성도 높은 포스팅 데이터를 생성하세요."
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    try:
        res = requests.post(url, json=payload, timeout=180)
        if res.status_code == 200:
            raw_response = res.json()['candidates'][0]['content']['parts'][0]['text']
            
            # JSON 데이터 정제 로직 (안전한 추출 및 제어 문자 제거)
            json_str = raw_response.strip()
            
            # 마크다운 백틱 제거 (정규표현식을 이용해 중단 방지)
            if json_str.startswith("`" * 3):
                json_str = re.sub(r'^`{3}(?:json)?\s*', '', json_str)
                json_str = re.sub(r'\s*`{3}$', '', json_str)
            
            # JSON 파싱을 방해하는 특수 제어 문자 제거
            json_str = re.sub(r'[\x00-\x1F\x7F]', '', json_str)
            
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON 파싱 1차 실패 ({e}). 재정제 시도 중...", flush=True)
                # 중괄호 { } 사이의 내용만 추출하여 재시도
                match = re.search(r'(\{.*\})', json_str, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except:
                        pass
                raise e
    except Exception as e:
        print(f"AI 콘텐츠 생성 실패: {e}", flush=True)
    return None

# ==========================================
# 5. 최종 실행 및 워드프레스 포스팅
# ==========================================
def post_article(data, mid):
    """워드프레스 REST API를 통해 게시물을 발행합니다."""
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    # 태그 자동 매칭 및 생성
    tag_ids = []
    tags_raw = data.get('tags', '')
    if tags_raw:
        for tname in [t.strip() for t in tags_raw.split(',') if t.strip()]:
            try:
                r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth, timeout=10)
                tid = next((t['id'] for t in r.json() if t['name'] == tname), None) if r.status_code == 200 and isinstance(r.json(), list) else None
                if not tid:
                    cr = requests.post(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags", auth=auth, json={"name": tname}, timeout=10)
                    if cr.status_code == 201: tid = cr.json()['id']
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
        return res.status_code == 201
    except Exception as e:
        print(f"워드프레스 API 발행 오류: {e}", flush=True)
        return False

def main():
    if not GEMINI_API_KEY: 
        print("❌ GEMINI_API_KEY가 누락되었습니다.", flush=True); return

    # 설정 및 이전 데이터 로드
    user_links = load_external_links()
    recent_posts = get_recent_posts()
    scraper = NaverScraper()
    
    print("🚀 SEO 지능형 엔진 기동: 실시간 트렌드 분석 및 포스팅 시작...", flush=True)
    
    # 키워드 풀 구성
    jobs = [("101", "경제/비즈니스"), ("105", "IT/테크"), (None, "일반/생활")]
    pool = []
    for sid, cat in jobs:
        items = scraper.get_news_ranking(sid) if sid else scraper.get_blog_hot_topics()
        for i in items[:3]: pool.append({"kw": i, "cat": cat})
        time.sleep(1)

    if not pool:
        print("❌ 수집된 트렌드 데이터가 없습니다.", flush=True); return
    
    # 발행 대상 선정
    targets = random.sample(pool, 1) if IS_TEST else random.sample(pool, min(len(pool), 10))
    
    for idx, item in enumerate(targets):
        print(f"📝 [{idx+1}/{len(targets)}] '{item['kw']}' 포스팅 생성 중...", flush=True)
        
        # 1. AI 콘텐츠 생성
        data = generate_article(item['kw'], item['cat'], recent_posts, user_links)
        if not data:
            print("❌ AI 데이터 파싱 실패. 다음 키워드로 넘어갑니다.", flush=True); continue
        
        # 2. 이미지 생성 및 처리
        mid = None
        if data.get('image_prompt'):
            print("🎨 대표 이미지 생성 및 최적화(70% JPG) 중...", flush=True)
            img_data = generate_image_process(data['image_prompt'])
            if img_data:
                mid = upload_to_wp_media(img_data)
        
        # 3. 워드프레스 발행
        if post_article(data, mid):
            print(f"✅ 발행 성공: {data.get('title')}", flush=True)
        else:
            print("❌ 워드프레스 발행 실패", flush=True)
            
        # 스케줄 대기 (운영 모드일 경우)
        if not IS_TEST and idx < len(targets) - 1:
            wait = random.randint(900, 1800) # 15~30분 랜덤 대기
            print(f"⏳ 다음 포스팅까지 약 {wait//60}분 대기합니다...", flush=True)
            time.sleep(wait)

if __name__ == "__main__":
    main()
