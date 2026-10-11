import {Routes, Route} from 'react-router-dom'
import Landing from "./pages/Landing"
import Signin from "./pages/Signin"
import Signup from "./pages/Signup"
import Dashboard from "./pages/Dashboard"
import Scenarios from "./pages/Scenarios"
import './App.css'

function App() {
  
  return (
    <>
     <Routes>
      <Route path = "/" element = {<Landing/>}/>
      <Route path = "/Signin" element = {<Signin/>}/>
       <Route path = "/Signup" element = {<Signup/>}/> 
      <Route path = "/Dashboard" element = {<Dashboard/>}/>
      <Route path = "/scenarios" element = {<Scenarios/>}/>
      
     </Routes>
    
    </>
  )
}

export default App
