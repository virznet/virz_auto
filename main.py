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
# 3. 워드프레스 & 이미지 최적화
# ==========================================
def get_recent_posts():
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except Exception as e:
        print(f"최근 포스트 로드 오류: {e}", flush=True)
    return []

def generate_image_process(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    final_prompt = f"Professional photography for: {prompt}. High resolution, 8k, cinematic lighting. Strictly NO TEXT, NO LETTERS, NO WORDS, NO FONTS."
    payload = {"instances": [{"prompt": final_prompt}], "parameters": {"sampleCount": 1}}
    
    try:
        response = requests.post(url, json=payload, timeout=150)
        if response.status_code == 200:
            result = response.json()
            b64_data = result['predictions'][0]['bytesBase64Encoded']
            img_data = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_data))
            if img.mode != 'RGB': img = img.convert('RGB')
            out = io.BytesIO()
            img.save(out, format='JPEG', quality=70, optimize=True)
            return out.getvalue()
    except Exception as e:
        print(f"이미지 생성 중 예외 발생: {e}", flush=True)
    return None

def upload_to_wp_media(img_data):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=feat_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201: return res.json()['id']
    except Exception as e:
        print(f"미디어 업로드 실패: {e}", flush=True)
    return None

# ==========================================
# 4. 스마트 콘텐츠 생성 (JSON 오류 방지 강화)
# ==========================================
def generate_article(keyword, category, internal_posts, user_links):
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    internal_ref = "내 블로그 추천글 목록:\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in internal_posts]) if internal_posts else ""
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "본문에 포함할 외부 링크 목록:\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 3,000자 이상의 매우 상세한 블로그 글을 작성하세요.

[필수 사항: JSON 무결성]
- 응답은 반드시 유효한 JSON 형식이어야 합니다.
- 'content' 필드 내의 HTML 태그 속성에는 큰따옴표(") 대신 작은따옴표(')를 사용하세요. 
  예: <div class='wp-block-button'> (JSON 파싱 에러 방지 목적)
- 본문 내에 큰따옴표를 꼭 써야 한다면 반드시 이스케이프 처리하세요(\").

[SEO 가이드]
1. 내부 링크: 제공된 추천글 중 하나를 첫 H2 섹션 이후에 삽입.
2. 외부 링크: 제공된 외부 링크 2개를 본문 중간에 버튼 블록과 함께 배치.
3. AI 권위 링크: 관련성 높은 공신력 있는 외부 출처를 하단에 추가.

JSON 키: 'title', 'content', 'excerpt', 'tags', 'image_prompt'.
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n위 정보를 바탕으로 완성도 높은 JSON 데이터를 생성하세요."
    
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
            
            # JSON 정제 로직
            json_str = raw_response.strip()
            if json_str.startswith("```"):
                json_str = re.sub(r'^`{3}(?:json)?\s*', '', json_str)
                json_str = re.sub(r'\s*`{3}$', '', json_str)
            
            # 제어 문자 제거 (줄바꿈 \n은 유지해야 함)
            json_str = "".join(c for c in json_str if ord(c) >= 32 or c in '\n\r\t')

            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON 1차 파싱 실패: {e}. 긴급 복구 시도...", flush=True)
                # 따옴표 중복 문제 해결을 위한 정규표현식 (필드 값 내부의 이스케이프 안 된 따옴표 찾기)
                # 이 로직은 매우 복잡하므로, 가장 흔한 패턴인 HTML 속성 따옴표 문제를 수정 시도
                fixed_str = re.sub(r'(?<!\\)"', r'\"', json_str) # 모든 따옴표 이스케이프
                fixed_str = re.sub(r'^\\"|\\"$', '"', fixed_str) # 시작과 끝 따옴표 복구
                fixed_str = re.sub(r'\\":', '":', fixed_str) # 키값 콜론 복구
                fixed_str = re.sub(r',\\"', ',"', fixed_str) # 콤마 뒤 키값 복구
                fixed_str = re.sub(r'{\\"', '{"', fixed_str) # 시작 브레이스 뒤 키값 복구
                
                try:
                    return json.loads(fixed_str)
                except:
                    # 최후의 수단: 가장 깨끗한 JSON 블록만 추출
                    match = re.search(r'(\{.*\})', json_str, re.DOTALL)
                    if match: return json.loads(match.group(1))
                    raise e
    except Exception as e:
        print(f"AI 콘텐츠 생성 실패: {e}", flush=True)
    return None

# ==========================================
# 5. 최종 실행 및 워드프레스 포스팅
# ==========================================
def post_article(data, mid):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    tag_ids = []
    tags_raw = data.get('tags', [])
    if tags_raw:
        tag_names = tags_raw if isinstance(tags_raw, list) else [t.strip() for t in str(tags_raw).split(',') if t.strip()]
        for tname in tag_names:
            try:
                r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth, timeout=10)
                tags_data = r.json()
                tid = next((t['id'] for t in tags_data if str(t['name']).lower() == tname.lower()), None) if r.status_code == 200 and isinstance(tags_data, list) else None
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

    user_links = load_external_links()
    recent_posts = get_recent_posts()
    scraper = NaverScraper()
    
    print("🚀 SEO 지능형 엔진 기동...", flush=True)
    
    jobs = [("101", "경제/비즈니스"), ("105", "IT/테크"), (None, "일반/생활")]
    pool = []
    for sid, cat in jobs:
        items = scraper.get_news_ranking(sid) if sid else scraper.get_blog_hot_topics()
        for i in items[:3]: pool.append({"kw": i, "cat": cat})
    
    if not pool: return
    
    targets = random.sample(pool, 1) if IS_TEST else random.sample(pool, min(len(pool), 5))
    
    for idx, item in enumerate(targets):
        print(f"📝 [{idx+1}/{len(targets)}] '{item['kw']}' 처리 중...", flush=True)
        data = generate_article(item['kw'], item['cat'], recent_posts, user_links)
        if not data: continue
        
        mid = None
        if data.get('image_prompt'):
            print("🎨 이미지 생성 중...", flush=True)
            img_data = generate_image_process(data['image_prompt'])
            if img_data: mid = upload_to_wp_media(img_data)
        
        if post_article(data, mid):
            print(f"✅ 발행 성공: {data.get('title')}", flush=True)
        else:
            print("❌ 발행 실패", flush=True)
            
        if not IS_TEST and idx < len(targets) - 1:
            wait = random.randint(300, 600)
            print(f"⏳ 대기 중 ({wait//60}분)...", flush=True)
            time.sleep(wait)

if __name__ == "__main__":
    main()
