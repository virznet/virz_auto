import os
import random
import time
import requests
import json
import base64
import re
import io
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from PIL import Image

# ==========================================
# 1. 환경 변수 및 설정 (2026-02-13 기준)
# ==========================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
WP_USERNAME = os.environ.get('WP_USERNAME', '').strip()
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD', '').replace(' ', '').strip()
WP_BASE_URL = "https://virz.net" 

# 테스트 모드 설정 (시크릿에서 TEST_MODE를 true로 설정 시 1개만 즉시 발행)
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# ==========================================
# 2. 데이터 로드 및 수집
# ==========================================
def load_external_links():
    """links.json 파일에서 사용자 정의 링크를 불러옵니다."""
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
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            return [t.text.strip() for t in soup.select(".rankingnews_list .list_title")[:10]]
        except Exception as e:
            print(f"뉴스 수집 오류: {e}", flush=True)
            return []

    def get_blog_hot_topics(self):
        try:
            res = requests.get("https://section.blog.naver.com/HotTopicList.naver", headers=self.headers, timeout=15)
            res.encoding = 'utf-8'
            return [t.text.strip() for t in BeautifulSoup(res.text, 'html.parser').select(".list_hottopic .desc")[:10]]
        except Exception as e:
            print(f"블로그 수집 오류: {e}", flush=True)
            return []

# ==========================================
# 3. 워드프레스 & 이미지 최적화 (JPG 70%)
# ==========================================
def get_recent_posts():
    """내부 링크용 최근 포스트 목록 가져오기"""
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except Exception as e:
        print(f"최근 포스트 로드 오류: {e}", flush=True)
    return []

def generate_image_process(prompt):
    """Gemini 2.5 Flash Image를 사용하여 썸네일 생성 및 JPG 70% 압축"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent?key={GEMINI_API_KEY}"
    
    # 글자가 없는 순수 이미지를 위한 프롬프트 강화
    final_prompt = f"Professional photography for: {prompt}. High resolution, 8k, cinematic lighting. Strictly NO TEXT, NO LETTERS, NO WORDS, NO FONTS."
    
    payload = {
        "contents": [{"parts": [{"text": final_prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]}
    }
    
    try:
        response = requests.post(url, json=payload, timeout=150)
        if response.status_code == 200:
            result = response.json()
            inline_data = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('inlineData', {}).get('data')
            if inline_data:
                img_data = base64.b64decode(inline_data)
                
                # 이미지 압축 처리 (Pillow)
                img = Image.open(io.BytesIO(img_data))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                out = io.BytesIO()
                img.save(out, format='JPEG', quality=70, optimize=True)
                return out.getvalue()
        print(f"이미지 생성 실패 (상태코드): {response.status_code}", flush=True)
    except Exception as e:
        print(f"이미지 생성 중 예외 발생: {e}", flush=True)
    return None

def upload_to_wp_media(img_data):
    """워드프레스 미디어 라이브러리 업로드"""
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
# 4. 스마트 콘텐츠 생성 (지능형 링크 분산)
# ==========================================
def generate_article(keyword, category, internal_posts, user_links):
    """지능형 링크 전략이 적용된 3,000자 포스팅 생성"""
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    # 내부 링크 후보
    internal_ref = "내 블로그 추천글:\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in internal_posts]) if internal_posts else ""
    
    # 사용자 외부 링크 랜덤 2개 선택
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "본문 중간 삽입용 외부 링크:\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 분야 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 3,000자 이상의 깊이 있는 정보를 제공하세요.

[SEO 링크 분산 배치 전략]
1. 내부 링크(1개): 제공된 내 블로그 글 중 하나를 본문의 첫 번째 H2 섹션 이후에 자연스럽게 삽입하세요.
2. 사용자 지정 외부 링크(2개): 제공된 링크들을 본문 중간중간(H2~H3 섹션 사이)에 분산 배치하세요. 하나는 텍스트 링크, 하나는 버튼 블록으로 만드세요.
3. AI 권위 외부 링크(1개): 주제와 관련된 위키백과나 공식 뉴스 URL을 당신이 직접 찾아 본문 하단에 추가하세요.

[필수 사항]
- 인사말, 날짜, 자기소개 금지. 바로 본론 시작.
- 구텐베르크 블록(HTML 주석) 형식을 완벽히 준수할 것.
- 썸네일용 영문 프롬프트 (글자/숫자 배제 강조).
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n위 링크들을 본문에 자연스럽게 녹여서 JSON으로 응답하세요."
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    try:
        res = requests.post(url, json=payload, timeout=180)
        if res.status_code == 200:
            raw = res.json()['candidates'][0]['content']['parts'][0]['text']
            return json.loads(re.search(r'\{.*\}', raw, re.DOTALL).group())
    except Exception as e:
        print(f"콘텐츠 생성 실패: {e}", flush=True)
    return None

# ==========================================
# 5. 실행 및 제어
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ GEMINI_API_KEY가 없습니다.", flush=True); return

    # 1. 링크 리스트 로드
    user_links = load_external_links()
    recent_posts = get_recent_posts()
    
    scraper = NaverScraper()
    print("🚀 SEO 지능형 엔진 기동: 실시간 트렌드 분석 중...", flush=True)
    
    # 2. 키워드 수집
    jobs = [("101", "경제"), ("105", "IT/테크"), ("103", "생활/문화"), (None, "일반")]
    pool = []
    for sid, cat in jobs:
        items = scraper.get_news_ranking(sid) if sid else scraper.get_blog_hot_topics()
        for i in items[:3]: pool.append({"kw": i, "cat": cat})
        time.sleep(1)

    if not pool: return
    
    # 3. 타겟 선정
    targets = random.sample(pool, 1) if IS_TEST else random.sample(pool, min(len(pool), 10))
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    for idx, item in enumerate(targets):
        print(f"📝 [{idx+1}/{len(targets)}] '{item['kw']}' 지능형 포스팅 생성...", flush=True)
        
        # 콘텐츠 생성
        data = generate_article(item['kw'], item['cat'], recent_posts, user_links)
        if not data: continue
        
        # 이미지 처리
        mid = None
        if data.get('image_prompt'):
            print("🎨 대표 이미지 생성 및 70% 압축 중...", flush=True)
            img_data = generate_image_process(data['image_prompt'])
            if img_data:
                mid = upload_to_wp_media(img_data)
        
        # 태그 처리
        tag_ids = []
        if data.get('tags'):
            for tname in [t.strip() for t in data['tags'].split(',')]:
                try:
                    r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth)
                    tid = next((t['id'] for t in r.json() if t['name'] == tname), None) if r.status_code == 200 else None
                    if not tid:
                        cr = requests.post(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags", auth=auth, json={"name": tname})
                        if cr.status_code == 201: tid = cr.json()['id']
                    if tid: tag_ids.append(tid)
                except: continue

        # 최종 발행
        payload = {
            "title": data['title'], 
            "content": data['content'], 
            "excerpt": data['excerpt'],
            "tags": tag_ids, 
            "featured_media": mid, 
            "status": "publish"
        }
        
        try:
            post_res = requests.post(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts", auth=auth, json=payload, timeout=40)
            if post_res.status_code == 201:
                print(f"✅ 발행 성공: {data['title']}", flush=True)
            else:
                print(f"❌ 발행 실패: {post_res.status_code}", flush=True)
        except Exception as e:
            print(f"❗ 포스팅 중 예외 발생: {e}", flush=True)
            
        # 스케줄 대기
        if not IS_TEST and idx < len(targets) - 1:
            wait = random.randint(900, 1800) # 15분 ~ 30분
            print(f"⏳ 다음 포스팅까지 {wait//60}분 대기합니다...", flush=True)
            time.sleep(wait)

if __name__ == "__main__":
    main()
