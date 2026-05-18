import streamlit as st
import pandas as pd
import re
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from streamlit_option_menu import option_menu
from streamlit_extras.metric_cards import style_metric_cards
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

st.set_page_config(
    page_title="OrderFlow Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for modern UI ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Poppins', sans-serif;
    }

   .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }

   .sub-header {
        color: #888;
        font-size: 1rem;
        margin-bottom: 2rem;
    }

   .stButton > button {
        border-radius: 12px;
        border: none;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: 600;
        transition: all 0.3s ease;
    }

   .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
    }

   .css-1d391kg {
        background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
    }

    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: 700;
    }

   .order-card {
        padding: 1.5rem;
        border-radius: 16px;
        background: rgba(102, 126, 234, 0.1);
        border: 1px solid rgba(102, 126, 234, 0.2);
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Database Setup ---
engine = create_engine("sqlite:///orders.db", connect_args={"check_same_thread": False})
Base = declarative_base()
Session = sessionmaker(bind=engine)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    order_id = Column(String)
    customer = Column(String)
    phone = Column(String)
    product = Column(String)
    qty = Column(Integer)
    price = Column(Float)
    status = Column(String)
    order_date = Column(DateTime)
    notes = Column(Text)

Base.metadata.create_all(engine)

STATUS_COLORS = {
    "Pending": "#FFA500",
    "Packed": "#1E90FF",
    "Shipped": "#9370DB",
    "Delivered": "#32CD32",
    "Cancelled": "#FF6347"
}

STATUS_ICONS = {
    "Pending": "⏳",
    "Packed": "📦",
    "Shipped": "🚚",
    "Delivered": "✅",
    "Cancelled": "❌"
}

# --- Helper Functions ---
def parse_whatsapp_message(text):
    patterns = {
        "name": r"(?:name|naam|customer)[:\-]\s*([A-Za-z\s]+)",
        "phone": r"(?:phone|contact|#|mobile)[:\-]\s*([+\d\s\-\(\)]{10,})",
        "product": r"(?:product|item|order)[:\-]\s*([^\n]+)",
        "qty": r"(?:qty|quantity|qnt|x)[:\-]\s*(\d+)",
        "price": r"(?:price|amount|rs|pkr|total)[:\-]\s*([\d,]+)"
    }
    data = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            data[key] = match.group(1).strip()
    numbers = re.findall(r'\d+', text)
    if "qty" not in data and numbers:
        data["qty"] = numbers[0]
    if "price" not in data and len(numbers) > 1:
        data["price"] = numbers[-1]
    return data

def load_orders():
    session = Session()
    df = pd.read_sql(session.query(Order).statement, session.bind)
    session.close()
    return df

def add_order(customer, phone, product, qty, price, notes=""):
    session = Session()
    count = session.query(Order).count()
    new_order = Order(
        order_id=f"ORD{count+1:04d}",
        customer=customer,
        phone=phone,
        product=product,
        qty=int(qty),
        price=float(price),
        status="Pending",
        order_date=datetime.now(),
        notes=notes
    )
    session.add(new_order)
    session.commit()
    session.close()

def update_orders(df):
    session = Session()
    for _, row in df.iterrows():
        order = session.query(Order).filter_by(id=row['id']).first()
        if order:
            order.status = row['status']
            order.qty = int(row['qty'])
            order.price = float(row['price'])
            order.customer = row['customer']
            order.product = row['product']
    session.commit()
    session.close()

# --- Sidebar Navigation ---
with st.sidebar:
    st.markdown("<h2 style='text-align: center;'>🚀 OrderFlow Pro</h2>", unsafe_allow_html=True)
    st.markdown("---")

    selected = option_menu(
        menu_title=None,
        options=["Dashboard", "Add Order", "Manage Orders", "Analytics", "Export"],
        icons=["speedometer2", "plus-circle", "list-check", "bar-chart", "download"],
        default_index=0,
        styles={
            "container": {"padding": "0!important", "background-color": "transparent"},
            "icon": {"color": "#667eea", "font-size": "18px"},
            "nav-link": {"font-size": "16px", "text-align": "left", "margin": "5px 0", "border-radius": "12px"},
            "nav-link-selected": {"background": "linear-gradient(90deg, #667eea 0%, #764ba2 100%)"},
        }
    )

    st.markdown("---")
    st.caption("💡 Tip: Paste WhatsApp messages for auto-fill")
    st.caption("📊 Data auto-saves to SQLite")

# --- Main Content ---
df = load_orders()

# Dashboard
if selected == "Dashboard":
    st.markdown('<div class="main-header">Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Your business at a glance</div>', unsafe_allow_html=True)

    if df.empty:
        st.info("👋 Welcome! Add your first order to see analytics here.")
    else:
        df["revenue"] = df["price"] * df["qty"]
        today = datetime.now().date()
        today_orders = df[df["order_date"].dt.date == today]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Orders", len(df), delta=f"+{len(today_orders)} today")
        col2.metric("Revenue", f"PKR {df['revenue'].sum():,.0f}", delta=f"PKR {today_orders['revenue'].sum():,.0f} today")
        col3.metric("Avg Order Value", f"PKR {df['revenue'].mean():,.0f}")
        col4.metric("Delivered Rate", f"{len(df[df['status']=='Delivered'])/len(df)*100:.1f}%")
        style_metric_cards(border_radius=16)

        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown("### 📈 Revenue Trend")
            daily = df.groupby(df["order_date"].dt.date)["revenue"].sum().reset_index()
            fig = px.area(daily, x="order_date", y="revenue",
                         color_discrete_sequence=["#667eea"],
                         template="plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white")
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.markdown("### 📊 Order Status")
            status_counts = df["status"].value_counts()
            fig = go.Figure(data=[go.Pie(
                labels=status_counts.index,
                values=status_counts.values,
                hole=.4,
                marker_colors=[STATUS_COLORS[s] for s in status_counts.index]
            )])
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), showlegend=True)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 🔥 Recent Orders")
        recent = df.sort_values("order_date", ascending=False).head(5)
        for _, row in recent.iterrows():
            st.markdown(f"""
            <div class="order-card">
                <b>{row['customer']}</b> • {row['product']}
                <span style="float: right; color: {STATUS_COLORS[row['status']]}">
                    {STATUS_ICONS[row['status']]} {row['status']}
                </span><br>
                <small>PKR {row['revenue']:,.0f} • {row['order_date'].strftime('%d %b %Y, %I:%M %p')}</small>
            </div>
            """, unsafe_allow_html=True)

# Add Order
elif selected == "Add Order":
    st.markdown('<div class="main-header">Add New Order</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])

    with col1:
        with st.container():
            st.markdown("#### 📱 Paste WhatsApp Message")
            msg = st.text_area("", height=120, placeholder="Name: Ali Khan\nProduct: Nike Shoes\nQty: 2\nPrice: 5000\nPhone: 03001234567")

            if st.button("✨ Auto-Fill Fields", use_container_width=True):
                parsed = parse_whatsapp_message(msg)
                st.session_state.parsed_data = parsed
                st.success("Fields extracted! Review below.")

        parsed_data = st.session_state.get("parsed_data", {})

        with st.form("order_form", clear_on_submit=True):
            st.markdown("#### ✍️ Order Details")
            col_a, col_b = st.columns(2)
            customer = col_a.text_input("Customer Name", value=parsed_data.get("name", ""))
            phone = col_b.text_input("Phone", value=parsed_data.get("phone", ""))
            product = st.text_input("Product", value=parsed_data.get("product", ""))

            col_c, col_d = st.columns(2)
            qty = col_c.number_input("Quantity", min_value=1, value=int(parsed_data.get("qty", 1)))
            price = col_d.number_input("Price (PKR)", min_value=0.0, value=float(parsed_data.get("price", 0)))
            notes = st.text_area("Notes", height=80)

            if st.form_submit_button("➕ Create Order", type="primary", use_container_width=True):
                if customer and phone and product:
                    add_order(customer, phone, product, qty, price, notes)
                    st.balloons()
                    st.success(f"Order created for {customer}!")
                    st.session_state.parsed_data = {}
                else:
                    st.error("Please fill required fields")

    with col2:
        st.markdown("#### 💡 Pro Tips")
        st.info("""
        **Fast Input Format:**
