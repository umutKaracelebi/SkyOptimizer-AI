import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import HomePage from '@/pages/HomePage';
import OptimizerPage from '@/pages/OptimizerPage';
import AboutPage from '@/pages/AboutPage';

function App() {
  return (
    <Router>
      <div className="dark">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/optimizer" element={<OptimizerPage />} />
          <Route path="/about" element={<AboutPage />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
